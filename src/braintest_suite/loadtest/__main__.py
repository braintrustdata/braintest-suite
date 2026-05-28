from dotenv import load_dotenv
from braintest_suite.config import load_config
from braintest_suite.loadtest import run

load_dotenv()
raise SystemExit(0 if run(load_config()) else 1)
