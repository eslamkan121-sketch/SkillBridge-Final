from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uvicorn

uvicorn.run('app.main:app', host='0.0.0.0', port=8000)