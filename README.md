# improvingGraphBin2
Bioinformatics Institute Autumn 2020 Project: Improving binning of metagenomic data.

## Purpose and objectives of project
### Purpose
Purpose of the project was to explore label propagation algorithm for metagenomic binning which is used in GraphBin2 and to make an attempt to improve this approach.

### Objectives
1. Explore workflow of [GraphBin2 binning tool](https://github.com/Vini2/GraphBin2)
2. Gather binning statistics including detailed information about intermediate binning results from GraphBin2.
3. Identify advantages and disadvantages of GraphBin2.
4. Make an attempt to improve GraphBin2.

### Future development
Obtained data may help to implement efficient binning algorithm with usage of SPAdes API.

## List of programs used in project
* Improved GraphBin2 (works with SPAdes assemblies)

### Binning evaluation
* Metaquast (gold standart file creation)
* Amber (binning benchmark)

### Binners
* [Metabat2](https://bitbucket.org/berkeleylab/metabat/src/master/) 
* [CONCOCT](https://github.com/BinPro/CONCOCT)
* [MaxBin2](https://sourceforge.net/projects/maxbin2/)
* [BinSanity](https://github.com/edgraham/BinSanity)
* [DAS_tool](https://github.com/cmks/DAS_Tool)
* [GraphBin2](https://github.com/Vini2/GraphBin2)

### Accessory tools
* convert_bins.py (binning files manipulation)
* compare_binnings.py (basic binning comparison)

## Installation
### Dependencies
* python>=3.7.1
* biopython>=1.72
* python-igraph>=0.7.1
* tqdm
* pandas>=1.1.14

### Installation using conda
```bash
git clone https://github.com/GinGin3203/improvingGraphBin2.git GraphBin2_improved
conda env create environment.yml
conda activate graphbin2
```


