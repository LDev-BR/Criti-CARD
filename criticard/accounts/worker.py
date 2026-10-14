"""Run with python -m criticard.accounts.worker after database migrations."""
import argparse
import logging
import signal
import threading

from sqlalchemy.exc import SQLAlchemyError

from criticard import create_app
from . import mail

logger = logging.getLogger("criticard.accounts.worker")


def run_worker(app, stop_event, interval=30, batch_size=50):
    if interval < 10 or not 1 <= batch_size <= 1000:
        raise ValueError("Use intervalo de pelo menos 10 segundos e lote de 1 a 1000 emails.")
    try:
        with app.app_context():
            settings = mail._settings()
            if settings is None or settings["backend"] != "smtp":
                logger.error("O worker de email precisa de transporte SMTP configurado.")
                return 2
    except (mail.MailConfigurationError, ValueError, OSError):
        logger.error("A configuração do worker de email está incompleta.")
        return 2
    while not stop_event.is_set():
        try:
            with app.app_context():
                mail.send_pending(batch_size, stop_event=stop_event)
        except (SQLAlchemyError, OSError):
            logger.warning("O worker de email não conseguiu processar a fila; tentará novamente.")
        if stop_event.wait(interval):
            break
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Entregar emails pendentes de conta por SMTP.")
    parser.add_argument("--interval", type=int, default=30, help="Intervalo entre lotes em segundos (mínimo 10).")
    parser.add_argument("--limit", type=int, default=50, help="Máximo de emails por lote (1 a 1000).")
    args = parser.parse_args(argv)
    if args.interval < 10 or not 1 <= args.limit <= 1000:
        parser.error("Use --interval >= 10 e --limit entre 1 e 1000.")
    stop = threading.Event()
    def shutdown(_signum, _frame):
        stop.set()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    return run_worker(create_app(), stop, args.interval, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
