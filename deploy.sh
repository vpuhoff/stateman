PYPIPASS="$(keylocker read pypi_password)"
PYPIUSER="$(keylocker read pypi_user)"
poetry publish --username "${PYPIUSER}" --password "${PYPIPASS}" --build