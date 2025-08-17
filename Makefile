format:
	black --preview .
	isort --profile black --line-length 100 .

lint:
	black --check --preview .
	isort --check-only --profile black --line-length 100 .
