#!/usr/bin/env python
import argparse
import pandas as pd
import os

parser = argparse.ArgumentParser(description="Comparison of number of binned contigs from 2 binnings. Output directory contains files with contigs binned only in first binner, contigs binned only in second binner and contigs binned in both")
parser.add_argument("binning_files", type=str, nargs=2, help="Binning files in tsv format to compare")
parser.add_argument("--skip", type=int, default=0, help="Number of rows to skip from begining of the file")
parser.add_argument("--output", type=str, help="Output directory name")

args = parser.parse_args()

outdir = args.output

df_1 = pd.read_table(args.binning_files[0], skiprows=args.skip, names=["Contig", "Bin", "Length"])
df_2 = pd.read_table(args.binning_files[1], skiprows=args.skip, names=["Contig", "Bin", "Length"])

df_merged = df_1.merge(df_2, how="outer", on=["Contig"])
contigs1 = set(df_1.Contig.values)
contigs2 = set(df_2.Contig.values)

try:
    os.mkdir(outdir)
except FileExistsError:
    pass


with open(f"{outdir}/binned_in1_only.tsv", "w") as file:
    for contig in contigs1 - contigs2:
        for _, row in df_1.query('Contig == @contig').iterrows():
            file.write(f"{row.Contig}\t{row.Length}\n")

with open(f"{outdir}/binned_in2_only.tsv", "w") as file:
    for contig in contigs2 - contigs1:
        for _, row in df_2.query('Contig == @contig').iterrows():
            file.write(f"{row.Contig}\t{row.Length}\n")

with open(f"{outdir}/binned_in_both.tsv", "w") as file:
    for contig in contigs2 | contigs1:
        for _, row in df_merged.query('Contig == @contig').iterrows():
            file.write(f"{row.Contig}\t{row.Bin_x}\t{row.Bin_y}\n")
