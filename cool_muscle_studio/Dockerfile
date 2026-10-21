ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.13-alpine3.21
FROM ${BUILD_FROM}

# Le frontend est servi tel quel (pas d'étape de build) : cmstudio/app/static.
# Les images multi-arch pourront être construites par GitHub Actions et publiées
# sur ghcr.io (voir docs/architecture.md §4.2) ; en attendant le Supervisor
# construit l'image sur l'appareil.

WORKDIR /app
COPY backend/pyproject.toml /app/backend/
# cmstudio/data/cml_reference.yaml est une copie de reference/cml_reference.yaml
# (le contexte de build du Supervisor est ce dossier ; un test vérifie l'égalité).
COPY backend/cmstudio /app/backend/cmstudio
RUN pip install --no-cache-dir /app/backend

ENV CMSTUDIO_REFERENCE=/app/backend/cmstudio/data/cml_reference.yaml

# Ingress : le serveur écoute sur 8099 et n'accepte que la passerelle 172.30.32.2
# (vérifié dans l'app quand SUPERVISOR_TOKEN est présent).
EXPOSE 8099
CMD ["python", "-m", "cmstudio.app", "--host", "0.0.0.0", "--port", "8099"]
