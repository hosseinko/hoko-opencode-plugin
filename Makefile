.PHONY: test test-serial
test:
	python3 scripts/run_tests.py

test-serial:
	python3 -m unittest discover -s scripts -p 'test_*.py'
