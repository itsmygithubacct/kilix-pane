PYTHON ?= python3
KITTY_INPUT_DIR ?= ../kitty-input
SOFT_RASTER_DIR ?= ../soft-raster
PRESENTER_DIR ?= ../kitty-frame-presenter

TEST_PATH := src:tests:$(KITTY_INPUT_DIR)/python/src:$(SOFT_RASTER_DIR)/python/src:$(PRESENTER_DIR)/src

.DEFAULT_GOAL := help
.PHONY: help all compile test demo doctor snapshot clean

help:
	@printf '%s\n' \
		'kilix-pane' \
		'' \
		'  make test      the suite (pixel tests skip without soft-raster)' \
		'  make demo      every widget, full screen' \
		'  make doctor    which backend this terminal gets, and why' \
		'  make snapshot  build/demo.png, a layout preview' \
		'' \
		'  KITTY_INPUT_DIR=$(KITTY_INPUT_DIR)' \
		'  SOFT_RASTER_DIR=$(SOFT_RASTER_DIR)  (build it: make -C $(SOFT_RASTER_DIR))'

all: compile

compile:
	$(PYTHON) -m compileall -q src

test:
	PYTHONPATH=$(TEST_PATH) $(PYTHON) -m unittest discover -s tests

demo:
	PYTHONPATH=$(TEST_PATH) $(PYTHON) -m kilix_pane demo

doctor:
	PYTHONPATH=$(TEST_PATH) $(PYTHON) -m kilix_pane doctor

snapshot:
	mkdir -p build
	PYTHONPATH=$(TEST_PATH) $(PYTHON) -m kilix_pane snapshot build/demo.png

clean:
	rm -rf build dist src/*.egg-info
	find . -name __pycache__ -prune -exec rm -rf {} +
