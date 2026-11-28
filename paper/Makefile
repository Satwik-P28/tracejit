# Build the manuscript and regenerate its tables from committed evidence.
#
#   make            tables, then the PDF
#   make tables     regenerate tables/ from benchmarks/results/**
#   make check      fail if a table disagrees with the evidence
#   make clean

PAPER := main
PYTHON ?= python3

.PHONY: all tables check pdf clean

all: tables pdf

tables:
	$(PYTHON) ../benchmarks/phase_af/build_tables.py --emit tables

check:
	$(PYTHON) ../benchmarks/phase_af/build_tables.py --check

pdf: tables
	pdflatex -interaction=nonstopmode $(PAPER)
	bibtex $(PAPER) || true
	pdflatex -interaction=nonstopmode $(PAPER)
	pdflatex -interaction=nonstopmode $(PAPER)

clean:
	rm -f $(PAPER).aux $(PAPER).bbl $(PAPER).blg $(PAPER).log $(PAPER).out $(PAPER).pdf
