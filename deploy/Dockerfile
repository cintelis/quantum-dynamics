# The quantum dashboard as a CPU-only container (no GPU needed; the GPU backend reports itself unavailable).
# Build context: the quantum/ folder.   docker build -f deploy/Dockerfile -t quantum-dashboard .
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# same versions as the WSL environment the dashboard was built and checked with
RUN pip install cudaq==0.16.0 numpy==2.5.4 scipy==1.18.1 matplotlib==3.11.2

RUN useradd --create-home --uid 10001 quantum
WORKDIR /app
COPY --chown=root:root dashboard.py dashboard.html explorer.html molecules.html chain.html landing.html admin.html nav.js vibchart.js \
     sim.py funnel.py transmon.py seed_runs.py ./
# all of data/: what the pages read, plus the raw perovskite database, catalogue and PubChem caches they were built from
COPY --chown=root:root data/ data/

# saved runs live in a volume; everything else is read-only
RUN mkdir -p /app/output/runs && chown quantum:quantum /app/output/runs
USER quantum
ENV HOST=0.0.0.0 PORT=8765 MPLCONFIGDIR=/tmp/mpl OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/schema', timeout=4)"
CMD ["python", "-W", "ignore", "dashboard.py"]
