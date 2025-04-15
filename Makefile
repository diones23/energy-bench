define install_items
	@install -d -m 755 $(2)
	@for file in $(wildcard $(1)); do \
		install -m 644 $$file $(2); \
	done
endef

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

	# Install main Python files using the unified helper
	$(call install_items,*.py,$(BASE_DIR))

	# Install files from the 'commands' and 'setups' directories
	$(call install_items,commands/*,$(BASE_DIR)/commands)
	$(call install_items,setups/*,$(BASE_DIR)/setups)

	# Install trial run file
	install -m 644 trial-run.yml $(BASE_DIR)

	# Create launcher script
	@echo '#!/bin/sh' > $(BIN_DIR)/$(NAME)
	@echo 'python3 $(BASE_DIR)/__main__.py "$$@"' >> $(BIN_DIR)/$(NAME)
	@chmod +x $(BIN_DIR)/$(NAME)

uninstall:
	rm -rf $(BASE_DIR)
	rm -f $(BIN_DIR)/$(NAME)

clean:
	cargo clean --manifest-path $(RAPL_DIR)/Cargo.toml

.PHONY: all install uninstall clean
.SILENT:
