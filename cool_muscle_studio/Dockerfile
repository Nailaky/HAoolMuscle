ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.13-alpine3.21
FROM ${BUILD_FROM}

# Étape 0 : squelette. Le serveur web (étape 1) et le frontend (build Vite)
# seront ajoutés ici ; les images multi-arch seront construites par GitHub
# Actions et publiées sur ghcr.io (voir docs/architecture.md §4.2).

WORKDIR /app
COPY backend/pyproject.toml /app/backend/
# cmstudio/data/cml_reference.yaml est une copie de reference/cml_reference.yaml
# (le contexte de build du Supervisor est ce dossier ; un test vérifie l'égalité).
COPY backend/cmstudio /app/backend/cmstudio
RUN pip install --no-cache-dir /app/backend

ENV CMSTUDIO_REFERENCE=/app/backend/cmstudio/data/cml_reference.yaml

# Remplacé à l'étape 1 par le serveur web de l'app.
CMD ["python", "-c", "print('Cool Muscle Studio : squelette, serveur à venir (étape 1)')"]
