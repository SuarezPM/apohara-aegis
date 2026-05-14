# Makefile — Apohara Aegis Policy Pack
# Targets: pack, clean, verify

TARBALL := pack.tar.gz
FILES   := install.sh README.md policy.yaml threat-model-summary.md VERSION

.PHONY: pack clean verify

pack: $(FILES)
	tar -czf $(TARBALL) $(FILES)
	@echo "Built $(TARBALL)"
	@ls -lh $(TARBALL)

clean:
	rm -f $(TARBALL)
	@echo "Cleaned."

verify: $(TARBALL)
	@echo "SHA-256: $$(sha256sum $(TARBALL))"
	@echo ""
	@echo "Contents:"
	@tar -tzf $(TARBALL)
