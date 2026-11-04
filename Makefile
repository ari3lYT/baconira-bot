.PHONY: test run demo
test:
	python -m unittest discover -s tests -v
run:
	python bot.py
demo:
	python tools/demo_transcript.py
