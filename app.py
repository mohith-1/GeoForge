import sys, os
from pathlib import Path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('PORT', '7860')
from viewer.server import app
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 7860))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
