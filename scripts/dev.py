#!/usr/bin/env python3
"""Launcher local (substitui docker-compose): sobe os microsserviços com um comando.

    python scripts/dev.py up [--restart]          # broker -> serviços -> gateway
    python scripts/dev.py only aportes custodia_retornos
    python scripts/dev.py kill  <servico>         # derruba um serviço (launcher rodando)
    python scripts/dev.py start <servico>         # sobe de novo um serviço derrubado
    python scripts/dev.py status                  # estado de cada serviço

Ctrl+C derruba tudo em ordem inversa (gateway -> serviços -> broker) sem deixar órfãos.
`kill`/`start`/`status` falam com o launcher por uma porta local de controle (DEV_CONTROL_PORT,
padrão 3090). Só usa a biblioteca padrão.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LOGS = RAIZ / "logs"

BROKER = "broker"
GATEWAY = "gateway"
NEGOCIO = ("identidade", "campanhas", "aportes", "custodia_retornos", "notificacao")
ORDEM = (BROKER, *NEGOCIO, GATEWAY)

HEALTH_TIMEOUT = float(os.environ.get("DEV_HEALTH_TIMEOUT", "15"))
STOP_TIMEOUT = 5.0
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = int(os.environ.get("DEV_CONTROL_PORT", "3090"))
BACKOFF_INICIAL = 1.0
BACKOFF_MAXIMO = 30.0
ESTAVEL_APOS = 20.0  # segundos no ar para zerar o backoff

CORES = ("36", "32", "33", "35", "34", "96", "92", "93", "95")  # códigos ANSI
RESET = "\033[0m"


# ----------------------------------------------------------------------------- funções puras


def carregar_servicos(path: Path | None = None) -> dict[str, int]:
    """nome -> porta, a partir de services.json."""
    bruto = json.loads((path or RAIZ / "services.json").read_text(encoding="utf-8"))
    return {nome: int(info["port"]) for nome, info in bruto.items()}


def url_servico(nome: str, path: Path | None = None) -> str:
    bruto = json.loads((path or RAIZ / "services.json").read_text(encoding="utf-8"))
    return str(bruto[nome]["url"]).rstrip("/")


def validar_nomes(nomes: list[str], conhecidos: dict[str, int]) -> list[str]:
    desconhecidos = [n for n in nomes if n not in conhecidos]
    if desconhecidos:
        raise ValueError(
            f"serviço(s) desconhecido(s): {', '.join(desconhecidos)}. "
            f"Disponíveis: {', '.join(conhecidos)}"
        )
    return nomes


def planejar_fases(nomes: list[str]) -> list[list[str]]:
    """Fases de subida: broker, depois serviços de negócio (em paralelo), depois gateway."""
    escolhidos = set(nomes)
    fases = [
        [n for n in (BROKER,) if n in escolhidos],
        [n for n in NEGOCIO if n in escolhidos],
        [n for n in (GATEWAY,) if n in escolhidos],
    ]
    return [f for f in fases if f]


def python_exec(raiz: Path = RAIZ) -> str:
    """Retorna o executável Python do virtualenv local se existir, senão sys.executable."""
    if sys.prefix != sys.base_prefix:
        return sys.executable
    venv_win = raiz / ".venv" / "Scripts" / "python.exe"
    if sys.platform == "win32" and venv_win.is_file():
        return str(venv_win)
    venv_posix = raiz / ".venv" / "bin" / "python"
    if venv_posix.is_file():
        return str(venv_posix)
    return sys.executable


def comando_servico(nome: str, raiz: Path = RAIZ) -> list[str]:
    """`<app>.main` se o app tiver main.py; senão o placeholder (só /health)."""
    py = python_exec(raiz)
    if (raiz / "apps" / nome / "src" / nome / "main.py").is_file():
        return [py, "-m", f"{nome}.main"]
    return [py, "-m", "shared.http.placeholder", nome]


def proximo_backoff(atual: float) -> float:
    return min(atual * 2, BACKOFF_MAXIMO)


def porta_livre(porta: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if sys.platform != "win32":
            # ignora TIME_WAIT de conexões antigas (o uvicorn faz o mesmo). No Windows,
            # SO_REUSEADDR deixaria "roubar" porta com listener ativo, então não se usa.
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, porta))
        except OSError:
            return False
        return True


def prefixo(nome: str, cor: str, largura: int, usar_cor: bool) -> str:
    texto = f"{nome:<{largura}} |"
    return f"\033[{cor}m{texto}{RESET}" if usar_cor else texto


def cor_habilitada() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def health_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=timeout) as r:  # noqa: S310
            return bool(r.status == 200)
    except (urllib.error.URLError, OSError, ValueError):
        return False


# ----------------------------------------------------------------------------- processos


@dataclass
class Servico:
    nome: str
    porta: int
    url: str
    cor: str
    proc: asyncio.subprocess.Process | None = None
    estado: str = "parado"  # parado | subindo | no ar | caiu | derrubado
    inicio: float = 0.0
    backoff: float = BACKOFF_INICIAL
    leitor: asyncio.Task[None] | None = None
    observador: asyncio.Task[None] | None = None
    manual: bool = field(default=False)  # derrubado de propósito (kill): não reiniciar


class Launcher:
    def __init__(self, nomes: list[str], reiniciar: bool = False) -> None:
        portas = carregar_servicos()
        validar_nomes(nomes, portas)
        self.nomes = [n for n in ORDEM if n in nomes]
        self.reiniciar = reiniciar
        self.usar_cor = cor_habilitada()
        self.largura = max(len(n) for n in self.nomes) if self.nomes else 0
        self.servicos = {
            n: Servico(n, portas[n], url_servico(n), CORES[i % len(CORES)])
            for i, n in enumerate(self.nomes)
        }
        self.encerrando = False
        self.parar = asyncio.Event()
        self.fases = planejar_fases(self.nomes)

    # -- saída ---------------------------------------------------------------------------

    def dizer(self, nome: str, msg: str) -> None:
        cor = self.servicos[nome].cor if nome in self.servicos else "0"
        print(f"{prefixo(nome, cor, self.largura, self.usar_cor)} {msg}", flush=True)

    def aviso(self, msg: str) -> None:
        marca = "\033[1;31m!!\033[0m" if self.usar_cor else "!!"
        print(f"{marca} {msg}", flush=True)

    async def _ler_saida(self, s: Servico, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        LOGS.mkdir(exist_ok=True)
        with (LOGS / f"{s.nome}.log").open("w", encoding="utf-8") as arquivo:
            while True:
                linha = await proc.stdout.readline()
                if not linha:
                    return
                texto = linha.decode("utf-8", errors="replace").rstrip()
                arquivo.write(texto + "\n")
                arquivo.flush()
                self.dizer(s.nome, texto)

    # -- ciclo de vida de um serviço -------------------------------------------------------

    async def iniciar(self, nome: str) -> None:
        s = self.servicos[nome]
        if not porta_livre(s.porta):
            raise RuntimeError(
                f"porta {s.porta} ({nome}) já está em uso. Sobrou processo de uma execução "
                "anterior? Encerre-o e tente de novo."
            )
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        venv_dir = RAIZ / ".venv"
        if venv_dir.is_dir():
            env["VIRTUAL_ENV"] = str(venv_dir)
            scripts_dir = venv_dir / ("Scripts" if sys.platform == "win32" else "bin")
            env["PATH"] = os.pathsep.join([str(scripts_dir), env.get("PATH", "")])
        env.setdefault("IDENTIDADE_AUTO_ATIVAR", "true")
        env.setdefault("KYC_HASH_SECRET", "segredo-kyc-hash-padrao-desenvolvimento-32b")
        env.setdefault("CAMPANHAS_SEED_DEMO", "true")
        env["PYTHONPATH"] = os.pathsep.join(
            [str(RAIZ / "apps" / nome / "src"), *filter(None, [env.get("PYTHONPATH")])]
        )
        kwargs: dict[str, object] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        s.manual = False
        s.estado = "subindo"
        s.inicio = time.monotonic()
        s.proc = await asyncio.create_subprocess_exec(
            *comando_servico(nome),
            cwd=RAIZ,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **kwargs,  # type: ignore[arg-type]
        )
        s.leitor = asyncio.create_task(self._ler_saida(s, s.proc))
        s.observador = asyncio.create_task(self._observar(s, s.proc))

    async def aguardar_health(self, nome: str) -> None:
        s = self.servicos[nome]
        assert s.proc is not None
        limite = time.monotonic() + HEALTH_TIMEOUT
        while time.monotonic() < limite:
            if s.proc.returncode is not None:
                raise RuntimeError(
                    f"{nome} terminou (código {s.proc.returncode}) antes de responder /health. "
                    f"Veja logs/{nome}.log"
                )
            if await asyncio.to_thread(health_ok, s.url):
                s.estado = "no ar"
                self.dizer(nome, f"no ar em {s.url} ({time.monotonic() - s.inicio:.1f}s)")
                return
            await asyncio.sleep(0.2)
        raise RuntimeError(f"{nome} não respondeu /health em {HEALTH_TIMEOUT:.0f}s")

    async def _observar(self, s: Servico, proc: asyncio.subprocess.Process) -> None:
        codigo = await proc.wait()
        if self.encerrando or s.proc is not proc:
            return
        if s.manual:
            s.estado = "derrubado"
            self.aviso(f"{s.nome} derrubado (kill). Use `dev.py start {s.nome}` para subir.")
            return
        s.estado = "caiu"
        self.aviso(f"{s.nome} MORREU inesperadamente (código {codigo}). Veja logs/{s.nome}.log")
        if not self.reiniciar:
            return
        if time.monotonic() - s.inicio > ESTAVEL_APOS:
            s.backoff = BACKOFF_INICIAL
        espera = s.backoff
        s.backoff = proximo_backoff(s.backoff)
        self.aviso(f"reiniciando {s.nome} em {espera:.0f}s...")
        await asyncio.sleep(espera)
        if self.encerrando or s.manual:
            return
        try:
            await self.iniciar(s.nome)
            await self.aguardar_health(s.nome)
        except RuntimeError as exc:
            self.aviso(str(exc))

    async def parar_servico(self, nome: str) -> None:
        s = self.servicos[nome]
        proc = s.proc
        if proc is None or proc.returncode is not None:
            return
        encerrar_processo(proc, forcar=False)
        try:
            await asyncio.wait_for(proc.wait(), STOP_TIMEOUT)
        except TimeoutError:
            self.aviso(f"{nome} não encerrou em {STOP_TIMEOUT:.0f}s; forçando.")
            encerrar_processo(proc, forcar=True)
            await proc.wait()
        if s.leitor:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(s.leitor, 2)
        s.estado = "parado"

    # -- subida e descida ---------------------------------------------------------------------

    async def subir(self) -> None:
        inicio = time.monotonic()
        for fase in self.fases:
            await asyncio.gather(*(self.iniciar(n) for n in fase))
            await asyncio.gather(*(self.aguardar_health(n) for n in fase))
        self.dizer_resumo(time.monotonic() - inicio)

    def dizer_resumo(self, segundos: float) -> None:
        print(f"\nTudo no ar em {segundos:.1f}s. Ctrl+C para encerrar.", flush=True)
        for s in self.servicos.values():
            print(f"  {s.nome:<{self.largura}}  {s.url}", flush=True)
        print(flush=True)

    async def derrubar_tudo(self) -> None:
        self.encerrando = True
        for fase in reversed(self.fases):
            await asyncio.gather(*(self.parar_servico(n) for n in fase))
        for s in self.servicos.values():
            if s.observador:
                s.observador.cancel()
        print("Todos os serviços foram encerrados.", flush=True)

    # -- controle (kill/start/status) -----------------------------------------------------------

    async def _controle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            linha = (await reader.readline()).decode("utf-8").strip()
            resposta = await self.executar(linha)
        except Exception as exc:  # resposta de erro, nunca derruba o launcher
            resposta = f"erro: {exc}"
        writer.write((resposta + "\n").encode("utf-8"))
        await writer.drain()
        writer.close()

    async def executar(self, linha: str) -> str:
        partes = linha.split()
        if not partes:
            return "erro: comando vazio"
        cmd, args = partes[0], partes[1:]
        if cmd == "status":
            return "\n".join(
                f"{s.nome:<{self.largura}}  {s.estado:<10} {s.url}" for s in self.servicos.values()
            )
        if cmd in ("kill", "start") and len(args) == 1:
            nome = args[0]
            if nome not in self.servicos:
                return (
                    f"erro: serviço '{nome}' não está sob este launcher ({', '.join(self.nomes)})"
                )
            s = self.servicos[nome]
            if cmd == "kill":
                s.manual = True
                await self.parar_servico(nome)
                s.estado = "derrubado"
                return f"{nome} derrubado"
            if s.proc is not None and s.proc.returncode is None:
                return f"{nome} já está no ar"
            await self.iniciar(nome)
            await self.aguardar_health(nome)
            return f"{nome} no ar em {s.url}"
        return f"erro: comando inválido '{linha}'. Use: status | kill <serviço> | start <serviço>"

    async def rodar(self) -> int:
        servidor = await asyncio.start_server(self._controle, CONTROL_HOST, CONTROL_PORT)
        instalar_sinais(self.parar)
        try:
            await self.subir()
            tarefa_parar = asyncio.create_task(self.parar.wait())
            await tarefa_parar
            print("\nEncerrando (ordem inversa)...", flush=True)
            return 0
        except RuntimeError as exc:
            self.aviso(str(exc))
            return 1
        finally:
            servidor.close()
            await self.derrubar_tudo()


def encerrar_processo(proc: asyncio.subprocess.Process, forcar: bool) -> None:
    """Termina o processo (e o grupo, no POSIX) sem deixar órfãos."""
    if proc.returncode is not None:
        return
    try:
        if sys.platform == "win32":
            if forcar:
                proc.kill()
            else:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(proc.pid, signal.SIGKILL if forcar else signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(ProcessLookupError):
            proc.kill()


def instalar_sinais(parar: asyncio.Event) -> None:
    """SIGINT/SIGTERM viram um pedido de parada ordenada."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
            loop.add_signal_handler(sig, parar.set)
    if sys.platform == "win32":
        # Windows não tem add_signal_handler; signal.signal roda na thread principal.
        for nome in ("SIGINT", "SIGBREAK"):
            if hasattr(signal, nome):
                signal.signal(
                    getattr(signal, nome),
                    lambda *_: loop.call_soon_threadsafe(parar.set),
                )


# ----------------------------------------------------------------------------- cliente de controle


def enviar_comando(comando: str) -> int:
    try:
        with socket.create_connection((CONTROL_HOST, CONTROL_PORT), timeout=30) as s:
            s.sendall((comando + "\n").encode("utf-8"))
            resposta = s.makefile("r", encoding="utf-8").read().strip()
    except OSError:
        print(
            "Nenhum launcher respondendo. Suba o sistema antes com `make dev` "
            f"(porta de controle {CONTROL_PORT}).",
            file=sys.stderr,
        )
        return 1
    print(resposta)
    return 1 if resposta.startswith("erro:") else 0


# ----------------------------------------------------------------------------- CLI


def montar_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Launcher local dos microsserviços")
    sub = ap.add_subparsers(dest="cmd")
    up = sub.add_parser("up", help="sobe tudo: broker, serviços, gateway")
    up.add_argument("--restart", action="store_true", help="reinicia serviço que morrer (backoff)")
    only = sub.add_parser("only", help="sobe só alguns serviços")
    only.add_argument("servicos", nargs="+")
    only.add_argument("--restart", action="store_true")
    for nome in ("kill", "start"):
        sub.add_parser(nome, help=f"{nome} de um serviço (com o launcher rodando)").add_argument(
            "servico"
        )
    sub.add_parser("status", help="estado de cada serviço")
    return ap


def main(argv: list[str]) -> int:
    args = montar_parser().parse_args(argv[1:] or ["up"])
    cmd = args.cmd or "up"
    if cmd in ("kill", "start"):
        return enviar_comando(f"{cmd} {args.servico}")
    if cmd == "status":
        return enviar_comando("status")

    reiniciar = bool(getattr(args, "restart", False)) or os.environ.get("DEV_RESTART") == "1"
    nomes = list(ORDEM) if cmd == "up" else args.servicos
    try:
        launcher = Launcher(nomes, reiniciar=reiniciar)
    except ValueError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    if sys.platform == "win32":
        os.system("")  # habilita ANSI no console legado
    return asyncio.run(launcher.rodar())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
