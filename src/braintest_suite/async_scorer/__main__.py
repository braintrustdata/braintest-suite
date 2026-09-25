from dotenv import load_dotenv

from braintest_suite.async_scorer.run import run

load_dotenv()
raise SystemExit(0 if run() else 1)
