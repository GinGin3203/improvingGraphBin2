#!/usr/bin/env python
import argparse
import pandas as pd


parser = argparse.ArgumentParser()
parser.add_argument("bin_filename", help="Path to file containing binning. Must have two fields: 'contig_name' and 'bin_id'")
parser.add_argument("--insep", default="\t", help="Input field separator")
parser.add_argument("--outsep", default=",", help="Output field separator")
parser.add_argument("--strip", default=False, action="store_true", help="Strip SPAdes-like contig names (NODE_1234_length_567_cov_8.991) to NODE_1234")
parser.add_argument("--del-rep", default=False, action="store_true", help="Ignore multiple binned contigs")
parser.add_argument("--skip", type=int, help="Number of rows to skip from file begining (usually 3 or 4 to skip biobox-header)")
parser.add_argument("--biobox-header", default=False, action="store_true", help="Add biobox format 0.9.1 header at the top of the file")
parser.add_argument("--sample-id", default="Sample", help="Sample id for biobox format")


args = parser.parse_args()

bin_file_df = pd.read_table(args.bin_filename, header=None,
                            sep=args.insep, names=["contig", "bin"],
                            skiprows=args.skip, engine="python")
current_bin = '' 
bin_cnt = 0
used_contigs = set()

if args.insep == "\\t":
    args.insep = "\t"
if args.outsep == "\\t":
    args.outsep = "\t"


# Add biobox format header
if args.biobox_header:
    print(f"@Version:0.9.1\n@SampleID:{args.sample_id}\n@@SEQUENCEID\tBINID")

bin_file_df = bin_file_df.sort_values("bin")
for idx, row in bin_file_df.iterrows():
    # Delete contig if belonging to multiple bins
    if row.contig in used_contigs and args.del_rep:
        continue
    if current_bin != row.bin:
        current_bin = row.bin
        bin_cnt += 1
    contig2paste = '_'.join(row.contig.split('_')[:2]) if args.strip else row.contig 
    print(f"{contig2paste}{args.outsep}{bin_cnt}")
    used_contigs.add(row.contig)
