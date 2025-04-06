NAME := energy-bench

PREFIX := $(HOME)
BASE_DIR := $(PREFIX)/.$(NAME)

# Rapl Interface Library
RAPL_DIR := rapl_interface
RAPL_SO := $(RAPL_DIR)/target/release/librapl_interface.so
RAPL_HEADER := $(RAPL_DIR)/rapl_interface.h
RAPL_JNI := $(RAPL_DIR)/RaplInterface.java

all: $(RAPL_SO)

$(RAPL_SO):
	cargo build --release --manifest-path $(RAPL_DIR)/Cargo.toml

install: $(RAPL_SO)
	install -d -m 755 $(BASE_DIR)

	install -m 755 $(RAPL_SO) $(BASE_DIR)
	install -m 644 $(RAPL_HEADER) $(BASE_DIR)
	install -m 644 $(RAPL_JNI) $(BASE_DIR)

uninstall:
	rm -rf $(BASE_DIR)

clean:
	cargo clean --manifest-path $(RAPL_DIR)/Cargo.toml

.PHONY: all install uninstall clean
.SILENT:
