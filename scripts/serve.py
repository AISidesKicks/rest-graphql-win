"""Serve the lab: REST, GraphQL and MCP in one process.

``--tls`` serves HTTPS on port 8443 with a locally trusted certificate, which
some MCP clients insist on. The certificate comes from mkcert when it is
installed, otherwise from openssl with a warning.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import load_settings  # noqa: E402

CERT_DIR_NAME = "certs"


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(command)}\n{result.stdout}\n{result.stderr}"
        )


def _mkcert_certificate(cert_dir: Path) -> tuple[Path, Path]:
    key = cert_dir / "key.pem"
    cert = cert_dir / "cert.pem"
    if key.exists() and cert.exists():
        return key, cert
    cert_dir.mkdir(parents=True, exist_ok=True)
    print("mkcert found, asking it for a certificate for 127.0.0.1 and localhost")
    try:
        _run(["mkcert", "-install"])
    except RuntimeError as exc:
        print(f"could not install the mkcert CA: {exc}")
    _run(
        [
            "mkcert",
            "-key-file",
            str(key),
            "-cert-file",
            str(cert),
            "127.0.0.1",
            "localhost",
            "::1",
        ]
    )
    print(f"certificate written to {cert}")
    return key, cert


def _openssl_certificate(cert_dir: Path) -> tuple[Path, Path]:
    key = cert_dir / "key.pem"
    cert = cert_dir / "cert.pem"
    if key.exists() and cert.exists():
        return key, cert
    cert_dir.mkdir(parents=True, exist_ok=True)
    print(
        "mkcert is not installed, falling back to an openssl self signed certificate.\n"
        "The browser will warn you, that is expected. Install mkcert for a trusted\n"
        "certificate: https://github.com/FiloSottile/mkcert"
    )
    config = cert_dir / "openssl.cnf"
    config.write_text(
        "[req]\ndistinguished_name=dn\nx509_extensions=v3_req\nprompt=no\n"
        "[dn]\nCN=localhost\n"
        "[v3_req]\nsubjectAltName=DNS:localhost,IP:127.0.0.1\nbasicConstraints=CA:FALSE\n"
        "keyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n",
        encoding="utf-8",
    )
    _run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "365",
            "-config",
            str(config),
        ]
    )
    print(f"certificate written to {cert}")
    return key, cert


def ensure_certificate(project_root: Path) -> tuple[Path, Path]:
    cert_dir = project_root / CERT_DIR_NAME
    if shutil.which("mkcert"):
        return _mkcert_certificate(cert_dir)
    return _openssl_certificate(cert_dir)


def main() -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Serve the lab")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--tls", action="store_true", help="serve HTTPS with a local certificate")
    parser.add_argument("--reload", action="store_true", help="reload on file changes")
    parser.add_argument(
        "--mcp",
        default=None,
        help="MCP exposure switch, all, rest, graphql, curated or a comma separated mix",
    )
    args = parser.parse_args()

    if args.mcp:
        os.environ["MCP_EXPOSURE"] = args.mcp

    import uvicorn

    ssl_keyfile = None
    ssl_certfile = None
    port = args.port
    scheme = "http"
    if args.tls:
        key, cert = ensure_certificate(settings.project_root)
        ssl_keyfile = str(key)
        ssl_certfile = str(cert)
        port = args.port if args.port != settings.port else settings.tls_port
        scheme = "https"

    print(f"lab is starting on {scheme}://{args.host}:{port}")
    print(f"  REST      {scheme}://{args.host}:{port}/api")
    print(f"  GraphiQL  {scheme}://{args.host}:{port}/graphql")
    print(f"  MCP       {scheme}://{args.host}:{port}{settings.mcp_path}")
    uvicorn.run(
        "app:app",
        host=args.host,
        port=port,
        reload=args.reload,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
