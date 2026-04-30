"""Entry point for the Council Finance application."""
from dotenv import load_dotenv
load_dotenv()

from council_finance import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
