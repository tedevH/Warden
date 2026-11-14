PY ?= .venv/bin/python
MOCK_PORT ?= 8100

.PHONY: setup mocks test worker

setup:   ## create .venv and install deps
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) -r requirements.txt
	$(PY) -m playwright install chromium
	@test -f .env || cp .env.example .env

mocks:   ## all mock sites on :$(MOCK_PORT) (admin at http://localhost:$(MOCK_PORT))
	MOCK_PORT=$(MOCK_PORT) $(PY) -m mocksites

test:    ## run the test suite
	$(PY) -m pytest -q

worker:  ## run one typed goal: make worker GOAL="read my inbox"
	$(PY) -m worker.browser_worker "$(GOAL)"
