"""Run the suite index or one application, using this interpreter's environment."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
APPLICATIONS = sorted(ROOT.glob('[0-9][0-9]-*'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('application', type=int, choices=range(10), nargs='?', default=0,
                        help='0: suite index; 1–9: individual application')
    parser.add_argument('--test', action='store_true', help='Run all suites in isolated processes')
    parser.add_argument('--port', type=int, help='Override the default local port')
    args = parser.parse_args()
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    if args.test:
        failed = False
        for app in APPLICATIONS:
            print(f'\nTesting {app.name}', flush=True)
            result = subprocess.run([sys.executable, '-m', 'pytest', 'tests', '-q'], cwd=app)
            failed |= result.returncode != 0
        raise SystemExit(int(failed))
    if args.application:
        import uvicorn
        sys.path.insert(0, str(APPLICATIONS[args.application-1]))
        uvicorn.run('app.main:app', host='127.0.0.1', port=args.port or 8000 + args.application)
        return
    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    app = FastAPI(title='Enterprise AI Systems')
    app.mount('/suite', StaticFiles(directory=ROOT/'suite'), name='suite')

    @app.get('/')
    def index():
        return FileResponse(ROOT/'suite/index.html')

    uvicorn.run(app, host='127.0.0.1', port=args.port or 8000)


if __name__ == '__main__':
    main()
