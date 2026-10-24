.PHONY: test test-serial
test:
	python3 scripts/run_tests.py

test-serial:
	python3 scripts/run_tests.py --jobs 1
