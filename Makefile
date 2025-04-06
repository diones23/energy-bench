NAME := energy-bench

PREFIX := $(HOME)
BASE_DIR := $(PREFIX)/.$(NAME)
BIN_DIR := $(PREFIX)/.local/bin

# Rapl Interface Library
RAPL_DIR := rapl_interface
RAPL_SO := $(RAPL_DIR)/target/release/librapl_interface.so
RAPL_HEADER := $(RAPL_DIR)/rapl_interface.h
RAPL_JNI := $(RAPL_DIR)/RaplInterface.java

all: $(RAPL_SO)

$(RAPL_SO):
	cargo build --release --manifest-path $(RAPL_DIR)/Cargo.toml

install: $(RAPL_SO)
	# Create necessary directories
	install -d -m 755 $(BASE_DIR)
	install -d -m 755 $(BIN_DIR)

	# Install RAPL interface files
	install -m 755 $(RAPL_SO) $(BASE_DIR)
	install -m 644 $(RAPL_HEADER) $(BASE_DIR)
	install -m 644 $(RAPL_JNI) $(BASE_DIR)
	
	# Install Python files
	cp -r __main__.py $(BASE_DIR)
	cp -r environments.py $(BASE_DIR)
	cp -r errors.py $(BASE_DIR)
	cp -r languages.py $(BASE_DIR)
	cp -r reporter.py $(BASE_DIR)
	cp -r runner.py $(BASE_DIR)
	cp -r spec.py $(BASE_DIR)
	cp -r workloads.py $(BASE_DIR)
	cp -r utils.py $(BASE_DIR)
	
	# Create launcher script
	echo '#!/bin/sh' > $(BIN_DIR)/$(NAME)
	echo 'python3 $(BASE_DIR)/__main__.py "$$@"' >> $(BIN_DIR)/$(NAME)
	chmod +x $(BIN_DIR)/$(NAME)
	
uninstall:
	rm -rf $(BASE_DIR)
	rm -f $(BIN_DIR)/$(NAME)

clean:
	cargo clean --manifest-path $(RAPL_DIR)/Cargo.toml

.PHONY: all install uninstall clean
.SILENT:
