PY ?= .venv/bin/python
MOCK_PORT ?= 8100
CHERT ?= npx --yes @trychert/facetime@0.1.0-beta.20

.PHONY: setup vault mocks orchestrator worker agent chert harness button demo redteam test box box-sim models enroll

setup:        ## create .venv, install deps and Chromium, create .env and the login vault
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) -r requirements.txt
	$(PY) -m playwright install chromium
	@test -f .env || cp .env.example .env
	@$(MAKE) --no-print-directory vault

vault:        ## create LEND_VAULT_KEY in .env (if missing) and store the mock-site test logins, encrypted
	@$(PY) -m orchestrator.vault init

mocks:        ## mock bank, mail, pizza and scam sites on :$(MOCK_PORT) (admin: http://localhost:$(MOCK_PORT))
	MOCK_PORT=$(MOCK_PORT) $(PY) -m mocksites

orchestrator: ## task API, safety gate, dashboard on http://127.0.0.1:8200
	$(PY) -m orchestrator

worker:       ## one typed goal without the orchestrator: make worker GOAL="read my inbox"
	$(PY) -m worker.browser_worker "$(GOAL)"

agent:        ## voice agent for the Chert line (needs LIVEKIT_* in .env.local and the orchestrator)
	$(PY) agent/agent.py dev

chert:        ## connect the Chert FaceTime line to the agent
	$(CHERT) dev

harness:      ## talk to Warden by typing (no Chert): same tools as the call
	$(PY) -m agent.harness

button:       ## open the approve-button page
	open http://127.0.0.1:8200/button

models:       ## download the face and voice matching models for the owner check (about 65 MB, runs locally)
	@mkdir -p models
	curl -sL -o models/yunet.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
	curl -sL -o models/sface.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx
	curl -sL -o models/speaker.onnx https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/wespeaker_en_voxceleb_resnet34.onnx

enroll:       ## make the next FaceTime Video call an enrollment call: Warden learns the caller as its owner
	@mkdir -p data/owner && touch data/owner/ENROLL && echo "Next call enrolls the owner. Call on FaceTime Video."

box:          ## safety box: connect the Arduino (button, knob, light) to Warden
	$(PY) hardware/bridge.py

box-sim:      ## safety box without an Arduino: type p (press), k 512 (knob), u (unlock)
	$(PY) hardware/bridge.py --sim

demo:         ## everything except Chert: mock sites + orchestrator + dashboard + button page + text harness
	@trap 'kill 0' INT TERM EXIT; \
	MOCK_PORT=$(MOCK_PORT) $(PY) -m mocksites & \
	CHERT_MODE=mock $(PY) -m orchestrator & \
	sleep 3; (open http://localhost:$(MOCK_PORT) http://127.0.0.1:8200/button http://127.0.0.1:8200 2>/dev/null || true); \
	$(PY) -m agent.harness

redteam:      ## attack Warden with every scam and print a scorecard (no keys, no AI)
	$(PY) -m orchestrator.redteam

test:         ## run the test suite
	$(PY) -m pytest -q -p no:warnings
