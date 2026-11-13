# =====================================================================
#  documentacion/Makefile — Atajos para compilar el documento
#  ---------------------------------------------------------------------
#  make            compila y deja SARU-documentacion.pdf
#  make ver        compila y abre el PDF
#  make limpio     borra intermedios (conserva el PDF final)
#  make todo-limpio borra intermedios y el PDF
#  make palabras   cuenta palabras de los capítulos
# =====================================================================

LATEXMK ?= latexmk
MAIN     = main
PDF      = SARU-documentacion.pdf
CAPITULOS = $(wildcard capitulos/*.tex)

.PHONY: all pdf ver limpio todo-limpio palabras

all: pdf

pdf:
	$(LATEXMK) -pdf $(MAIN).tex
	cp build/$(MAIN).pdf $(PDF)
	@echo ""
	@echo "  Listo: documentacion/$(PDF)"

ver: pdf
	@xdg-open $(PDF) >/dev/null 2>&1 || open $(PDF) >/dev/null 2>&1 || \
	 echo "Abre manualmente: $(PDF)"

limpio:
	$(LATEXMK) -c $(MAIN).tex
	@echo "Intermedios borrados."

todo-limpio:
	$(LATEXMK) -C $(MAIN).tex
	rm -f $(PDF)
	@echo "Todo borrado (vuelve a compilar con: make)."

palabras:
	@echo "Palabras por capitulo (aproximado):"
	@for f in $(CAPITULOS); do \
	  printf "  %-30s %6s\n" "$$f" "$$(detex "$$f" 2>/dev/null | wc -w)"; \
	done
