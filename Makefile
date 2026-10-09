# ==============================================================================
# Generador de RFD SIPECOM - Makefile
# Backend FastAPI + Frontend TypeScript Bun/Vite + Motor Word/PowerPoint
# Estandar Canónico: make help | install | build | dev | start | stop | status | test | check | clean
# ==============================================================================

ifeq ($(OS),Windows_NT)
  PY := .venv/Scripts/python.exe
else
  PY := .venv/bin/python
endif

PYTHON ?= python
PORT ?= 2122
PUERTO ?= $(PORT)
MODELO ?= haiku
PROVEEDOR ?= claude

.DEFAULT_GOAL := help
.NOTPARALLEL: dev start

.PHONY: help install build dev start stop restart status test check clean rebuild \
        dev-ui dev-backend doctor demo test-fast \
        ayuda instalar sync compilar web web-dev ui ejecutar run up servidor server limpiar lint test-rapido

# ==============================================================================
# 1. Ayuda y Descubrimiento
# ==============================================================================
help: ## Muestra este menu interactivo de comandos disponibles
	@echo ==============================================================================
	@echo   GENERADOR DE RFD SIPECOM - COMANDOS DISPONIBLES (Makefile Estandar)
	@echo ==============================================================================
	@echo   make install      - Instala entorno virtual, dependencias Python y web (bun)
	@echo   make build        - Compila la interfaz web TypeScript hacia generador_rfd/static
	@echo   make dev          - Inicia la aplicacion en http://127.0.0.1:$(PORT) y abre el navegador
	@echo   make start        - Inicia el servidor sin abrir el navegador (modo servicio)
	@echo   make dev-ui       - Inicia Vite en modo desarrollo para la interfaz web (web/)
	@echo   make stop         - Detiene procesos que esten escuchando en el puerto $(PORT)
	@echo   make restart      - Reinicia la aplicacion (stop seguido de dev)
	@echo   make status       - Diagnostica herramientas (doctor) y valida el puerto $(PORT)
	@echo   make test         - Ejecuta todas las pruebas unitarias (MODELO=$(MODELO))
	@echo   make check        - Chequeo rapido de pruebas locales sin LLMs externos
	@echo   make clean        - Borra caches (__pycache__, .pytest_cache) y temporales en salidas/
	@echo   make rebuild      - Limpia y recompila la interfaz web
	@echo ------------------------------------------------------------------------------
	@echo   Comandos especificos de dominio:
	@echo   make doctor       - Comprueba CLIs, CodeGraph y plantilla (PROVEEDOR=$(PROVEEDOR))
	@echo   make test-fast    - Pruebas rapidas sin llamadas a Claude ni a Codex
	@echo   make demo         - Genera el RFD de demostracion en salidas/
	@echo ==============================================================================

# ==============================================================================
# 2. Instalacion y Dependencias
# ==============================================================================
$(PY):
	@echo [*] Creando entorno virtual .venv...
	$(PYTHON) -m venv .venv
	@echo [*] Actualizando pip...
	$(PY) -m pip install -q --upgrade pip

install: $(PY) ## Instala dependencias de Python y de la interfaz web
	@echo [*] Instalando dependencias de Python con pip...
	$(PY) -m pip install -q -e ".[dev]"
	@echo [*] Instalando dependencias de interfaz web con bun...
	cd web && bun install

# ==============================================================================
# 3. Construccion y Compilacion
# ==============================================================================
build: ## Compila la interfaz TypeScript hacia generador_rfd/static
	@echo [*] Compilando interfaz web hacia generador_rfd/static...
	cd web && bun install && bun run build

# ==============================================================================
# 4. Desarrollo y Ejecucion
# ==============================================================================
dev: $(PY) ## Inicia la aplicacion con navegador en http://127.0.0.1:$(PORT)
	@echo [*] Iniciando GUI en http://127.0.0.1:$(PORT)...
	$(PY) -m generador_rfd gui --puerto $(PORT)

start: $(PY) ## Inicia el servidor sin abrir el navegador
	@echo [*] Iniciando servidor sin navegador en http://127.0.0.1:$(PORT)...
	$(PY) -m generador_rfd gui --puerto $(PORT) --sin-navegador

dev-ui: ## Inicia servidor de desarrollo Vite con recarga rapida
	@echo [*] Iniciando Vite en web/...
	cd web && bun run dev

dev-backend: start ## Alias de start

# ==============================================================================
# 5. Control de Procesos y Estado
# ==============================================================================
stop: ## Detiene procesos que ocupan el puerto configurado
	@echo [*] Deteniendo procesos en puerto $(PORT)...
	@$(PYTHON) -c "import subprocess, re; out = subprocess.getoutput('netstat -ano | findstr :$(PORT)'); pids = set(re.findall(r'LISTENING\s+(\d+)', out)); [subprocess.run(f'taskkill /F /PID {p}', shell=True) for p in pids] if pids else print('No hay procesos activos en el puerto $(PORT).')"

restart: stop dev ## Reinicia la aplicacion

status: doctor ## Diagnostica prerequisitos y verifica disponibilidad del puerto
	@echo [*] Verificando conectividad en http://127.0.0.1:$(PORT)...
	@$(PYTHON) -c "import urllib.request; \
	try: \
		with urllib.request.urlopen('http://127.0.0.1:$(PORT)', timeout=2) as r: \
			print(f'[OK] Servidor ACTIVO (Status: {r.status})'); \
	except Exception as e: \
		print(f'Servidor no responde en puerto $(PORT): {e}')"

doctor: $(PY) ## Comprueba CLIs, CodeGraph y plantilla
	$(PY) -m generador_rfd doctor --proveedor $(PROVEEDOR)

# ==============================================================================
# 6. Calidad, Pruebas y Limpieza
# ==============================================================================
test: $(PY) ## Ejecuta la suite de pruebas completa
	$(PY) -c "import os, subprocess, sys; os.environ['RFD_MODELO_TEST'] = '$(MODELO)'; sys.exit(subprocess.call([sys.executable, '-m', 'pytest', '-v']))"

test-fast: $(PY) ## Ejecuta pruebas rapidas (sin llamar a Claude ni a Codex)
	$(PY) -m pytest -v -m "not claude and not codex"

check: test-fast ## Chequeo rapido de calidad sin llamadas a LLMs

demo: $(PY) ## Genera el RFD de demostracion en salidas/
	$(PY) -m generador_rfd renderizar --datos ejemplos/rfd_demo.json --salida salidas/RFD_DEMO_SIPECOM.docx --publico

clean: ## Borra caches y archivos temporales generados
	@echo [*] Limpiando caches y salidas temporales...
	@$(PYTHON) -c "import pathlib, shutil; [shutil.rmtree(p, ignore_errors=True) for p in [*pathlib.Path('.').rglob('__pycache__'), pathlib.Path('.pytest_cache'), pathlib.Path('salidas/_entradas')]]; [p.unlink() for g in ('*.docx', '*.json', '*.revision.md') for p in pathlib.Path('salidas').glob(g)]; print('[OK] Limpieza completada.')"

rebuild: clean build ## Limpia y recompila la interfaz

# ==============================================================================
# 7. Red de Seguridad: Alias Universales (Compatibilidad Total)
# ==============================================================================
ayuda: help
instalar: install
sync: install
compilar: build
web: build
web-dev: dev-ui
ui: dev-ui
ejecutar: dev
run: dev
up: dev
servidor: start
server: start
limpiar: clean
lint: check
test-rapido: test-fast
