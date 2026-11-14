PY ?= .venv/bin/python
MOCK_PORT ?= 8100

.PHONY: setup mocks test

setup:   ## create .venv and install deps
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) -r requirements.txt
	@test -f .env || cp .env.example .env

mocks:   ## all mock sites on :$(MOCK_PORT) (admin at http://localhost:$(MOCK_PORT))
	MOCK_PORT=$(MOCK_PORT) $(PY) -m mocksites

test:    ## run the test suite
	$(PY) -m pytest -q
