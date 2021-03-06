#!/usr/bin/env python3

import csv
import time
import pandas as pd
import argparse
import re
import heapq
import itertools as it
import logging

from multiprocessing import Pool
from Bio import SeqIO
from igraph import *
from collections import defaultdict
from bidirectionalmap.bidirectionalmap import BidirectionalMap
from tqdm import tqdm


# Setup argument parser
#---------------------------------------------------

ap = argparse.ArgumentParser(description="""GraphBin2 Help. GraphBin2 is a tool which refines the binning results obtained from existing tools and, 
more importantly, is able to assign contigs to multiple bins. GraphBin2 uses the connectivity and coverage information from assembly graphs to 
adjust existing binning results on contigs and to infer contigs shared by multiple species.""")

ap.add_argument("--gold_standard", required=False, default="", help="gold standard file to check bin depth statistics")
ap.add_argument("--contigs", required=True, help="path to the contigs file")
ap.add_argument("--graph", required=True, help="path to the assembly graph file")
ap.add_argument("--paths", required=True, help="path to the contigs.paths file")
ap.add_argument("--binned", required=True, help="path to the .csv file with the initial binning output from an existing tool")
ap.add_argument("--output", required=True, help="path to the output folder")
ap.add_argument("--prefix", required=False, default='', help="prefix for the output file")
ap.add_argument("--depth", required=False, type=int, default=5, help="maximum depth for the breadth-first-search. [default: 5]")
ap.add_argument("--threshold", required=False, type=float, default=1.5, help="threshold for determining inconsistent vertices. [default: 1.5]")
ap.add_argument("--delimiter", required=False, type=str, default=",", help="delimiter for input/output results [default: , (comma)]")
ap.add_argument("--nthreads", required=False, type=int, default=8, help="number of threads to use. [default: 8]")
ap.add_argument("--add_true_depth", required=False, type=int, default=0, help="depth of adding true contigs with respect to BFS origin vertex")
ap.add_argument("--skip_ref", required=False, default=False, action="store_true", help="flag for skipping refinement stage")  #####
ap.add_argument("--cov_threshold", required=False, type=int, default=0, help="new threshold for contig coverage")    #####
ap.add_argument("--len_threshold", required=False, type=int, default=0, help="new threshold for contig length")    #####
ap.add_argument("--save_interval", required=False, type=int, default=0, help="indicates number of passed iterations needed for current binning save. (5 - save for every 5 iterations). 0 - disable intermediate binning saving") #####
ap.add_argument("--save_heap", required=False, default=False, action="store_true", help="save heap from every 'save_interval' iteration of label propagation") #####
ap.add_argument("--gold_standard", required=False, type=str, default="", help="path to the gold standard file for evaluation")
args = vars(ap.parse_args())

contigs_file = args["contigs"]
assembly_graph_file = args["graph"]
contig_paths = args["paths"]
contig_bins_file = args["binned"]
output_path = args["output"]
prefix = args["prefix"]
depth = args["depth"]
threshold = args["threshold"]
delimiter = args["delimiter"]
nthreads = args["nthreads"]

add_true_depth = args["add_true_depth"]
skip_ref = args["skip_ref"]
cov_threshold = args["cov_threshold"]
len_threshold = args["len_threshold"]
gold_standard = args["gold_standard"]
save_interval = args["save_interval"]
save_heap = args["save_heap"]

def write_heap(heap, contigs_map, filename):    #####
    """Write heap into tsv file which contains 5 fields: 'contig to bin', 'binned contig', 'bin of binned contig', 'distance between these two contigs', 'coverage difference'.
    Argument 'contigs_map' is map translating node number into initial contig number"""

    with open(filename, "w") as output_file:
        output_writer = csv.writer(output_file, delimiter="\t", quotechar='"', quoting=csv.QUOTE_MINIMAL)
        while True:
            try:
                out = list(heapq.heappop(heap).data)
                out[0] = f"NODE_{contigs_map[out[0]]}"
                out[1] = f"NODE_{contigs_map[out[1]]}"
                output_writer.writerow(out)
            except IndexError:
                return


def write_bins(bins, contig_names, filename):
    output_bins = []

    for k in range(len(bins)):
        for i in sorted(bins[k]):
            line = []
            line.append(contig_names[i])
            line.append(k+1)
            output_bins.append(line)

    with open(filename, mode='w') as output_file:
        output_writer = csv.writer(output_file, delimiter=delimiter, quotechar='"', quoting=csv.QUOTE_MINIMAL)

        for row in output_bins:
            output_writer.writerow(row)


def most_abundant_bins(gold_standard_df, query_df):
    """ A function to get mapping from gold standard bins to predicted bins """
    gs_df = gold_standard_df
    gs_df = gs_df[['SEQUENCEID', 'BINID', 'LENGTH']].rename(columns={'LENGTH': 'seq_length', 'BINID': 'genome_id'})


    query_w_length = pd.merge(query_df, gs_df.drop_duplicates('SEQUENCEID'), on='SEQUENCEID', sort=False)
    query_w_length.to_csv('~/query.csv', index=False)
    query_w_length_no_dups = query_w_length.drop_duplicates('SEQUENCEID')
    gs_df_no_dups = gs_df.drop_duplicates('SEQUENCEID')
    percentage_of_assigned_bps = query_w_length_no_dups['seq_length'].sum() / gs_df_no_dups['seq_length'].sum()
    percentage_of_assigned_seqs = query_w_length_no_dups.shape[0] / gs_df_no_dups['SEQUENCEID'].shape[0]

    # confusion table possibly with the same sequences in multiple bins
    query_w_length_mult_seqs = query_df.reset_index().merge(gs_df, on='SEQUENCEID', sort=False)


    if query_w_length.shape[0] < query_w_length_mult_seqs.shape[0]:
        query_w_length_mult_seqs.drop_duplicates(['index', 'genome_id'], inplace=True)
        confusion_df = query_w_length_mult_seqs.groupby(['BINID', 'genome_id'], sort=False).agg({'seq_length': 'sum', 'SEQUENCEID': 'count'}).rename(columns={'seq_length': 'genome_length', 'SEQUENCEID': 'genome_seq_counts'})

        most_abundant_genome_df = confusion_df.loc[confusion_df.groupby('BINID', sort=False)['genome_length'].idxmax()]
        most_abundant_genome_df = most_abundant_genome_df.reset_index()[['BINID', 'genome_id']]

        matching_genomes_df = pd.merge(query_w_length_mult_seqs, most_abundant_genome_df, on=['BINID', 'genome_id']).set_index('index')
        query_w_length_mult_seqs.set_index('index', inplace=True)
        difference_df = query_w_length_mult_seqs.drop(matching_genomes_df.index).groupby(['index'], sort=False).first()
        query_w_length = pd.concat([matching_genomes_df, difference_df])

        # Modify gs such that multiple binnings of the same sequence are not required
        matching_genomes_df = pd.merge(gs_df, query_w_length[['SEQUENCEID', 'genome_id']], on=['SEQUENCEID', 'genome_id'])
        matching_genomes_df = matching_genomes_df[['SEQUENCEID', 'genome_id', 'seq_length']].drop_duplicates(['SEQUENCEID', 'genome_id'])
        condition = gs_df_no_dups['SEQUENCEID'].isin(matching_genomes_df['SEQUENCEID'])
        difference_df = gs_df_no_dups[~condition]
        gs_df = pd.concat([difference_df, matching_genomes_df])

        # query_w_length_mult_seqs.reset_index(inplace=True)
        # query_w_length_mult_seqs = pd.merge(query_w_length_mult_seqs, most_abundant_genome_df, on=['BINID'])
        # grouped = query_w_length_mult_seqs.groupby(['index'], sort=False, as_index=False)
        # query_w_length = grouped.apply(lambda x: x[x['genome_id_x'] == x['genome_id_y'] if any(x['genome_id_x'] == x['genome_id_y']) else len(x) * [True]])
        # query_w_length = query_w_length.groupby(['index'], sort=False).first().drop(columns='genome_id_y').rename(columns={'genome_id_x': 'genome_id'})


    confusion_df = query_w_length.groupby(['BINID', 'genome_id'], sort=False).agg({'seq_length': 'sum', 'SEQUENCEID': 'count'}).rename(columns={'seq_length': 'genome_length', 'SEQUENCEID': 'genome_seq_counts'})

    most_abundant_genome_df = confusion_df.loc[confusion_df.groupby('BINID', sort=False)['genome_length'].idxmax()].reset_index().set_index('BINID')

    abundant_genome_dict = pd.Series((str(x) for x in most_abundant_genome_df.index), index=(str(x) for x in most_abundant_genome_df['genome_id'])).to_dict()
    return abundant_genome_dict




n_bins = 0


# Setup logger
#-----------------------
logger = logging.getLogger('GraphBin2')
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
consoleHeader = logging.StreamHandler()
consoleHeader.setFormatter(formatter)
consoleHeader.setLevel(logging.INFO)
logger.addHandler(consoleHeader)

# Setup output path for log file
#---------------------------------------------------

fileHandler = logging.FileHandler(output_path+"/"+prefix+"graphbin2.log")
fileHandler.setLevel(logging.DEBUG)
fileHandler.setFormatter(formatter)
logger.addHandler(fileHandler)


logger.info("Welcome to GraphBin2: Refined and Overlapped Binning of Metagenomic Contigs using Assembly Graphs.")
logger.info("This version of GraphBin2 makes use of the assembly graph produced by SPAdes which is based on the de Bruijn graph approach.")

logger.info("Input arguments:")
logger.info("Contigs file: "+contigs_file)
logger.info("Assembly graph file: "+assembly_graph_file)
logger.info("Contig paths file: "+contig_paths)
logger.info("Existing binning output file: "+contig_bins_file)
logger.info("Final binning output file: "+output_path)
logger.info("Depth: "+str(depth))
logger.info("Threshold: "+str(threshold))
logger.info("Number of threads: "+str(nthreads))

logger.info("GraphBin2 started")



start_time = time.time()

# Get length and coverage of contigs
#--------------------------------------------------------

contig_lengths = {}
coverages = {}

my_map = BidirectionalMap()

for index, record in enumerate(SeqIO.parse(contigs_file, "fasta")):
    start = 'NODE_'
    end = '_length'
    contig_num = int(re.search('%s(.*)%s' % (start, end), record.id).group(1))

    start = '_length_'
    end = '_cov'
    length = int(re.search('%s(.*)%s' % (start, end), record.id).group(1))

    start = '_cov_'
    end = ''
    coverage = int(float(re.search('%s(.*)%s' % (start, end), record.id).group(1)))

    contig_lengths[contig_num] = length
    coverages[contig_num] = coverage


# Get contig paths from contigs.paths
#-------------------------------------

paths = {}
segment_contigs = {}
node_count = 0

contig_names = {}

my_map = BidirectionalMap()

current_contig_num = ""

try:
    with open(contig_paths) as file:
        name = file.readline()
        path = file.readline()

        while name != "" and path != "":

                while ";" in path:
                    path = path[:-2]+","+file.readline()

                start = 'NODE_'
                end = '_length_'
                contig_num = str(int(re.search('%s(.*)%s' % (start, end), name).group(1)))

                segments = path.rstrip().split(",")

                if current_contig_num != contig_num:
                    my_map[node_count] = int(contig_num)
                    contig_names[node_count] = name.strip()
                    current_contig_num = contig_num
                    node_count += 1

                if contig_num not in paths:
                    paths[contig_num] = [segments[0], segments[-1]]

                for segment in segments:
                    if segment not in segment_contigs:
                        segment_contigs[segment] = set([contig_num])
                    else:
                        segment_contigs[segment].add(contig_num)

                name = file.readline()
                path = file.readline()

except:
    logger.error("Please make sure that the correct path to the contig paths file is provided.")
    logger.info("Exiting GraphBin2... Bye...!")
    sys.exit(1)

contigs_map = my_map
contigs_map_rev = my_map.inverse

logger.info("Total number of contigs available: "+str(node_count))

links = []
links_map = defaultdict(set)


## Construct the assembly graph
#-------------------------------

try:
    # Get links from assembly_graph_with_scaffolds.gfa
    with open(assembly_graph_file) as file:
        line = file.readline()

        while line != "":

            # Identify lines with link information
            if "L" in line:
                strings = line.split("\t")
                f1, f2 = strings[1]+strings[2], strings[3]+strings[4]
                links_map[f1].add(f2)
                links_map[f2].add(f1)
                links.append(strings[1]+strings[2]+" "+strings[3]+strings[4])
            line = file.readline()


    # Create graph
    assembly_graph = Graph()

    # Add vertices
    assembly_graph.add_vertices(node_count)

    # Create list of edges
    edge_list = []

    # Name vertices
    for i in range(node_count):
        assembly_graph.vs[i]["id"]= i
        assembly_graph.vs[i]["label"]= str(i)

    for i in range(len(paths)):
        segments = paths[str(contigs_map[i])]

        start = segments[0]
        start_rev = ""

        if start.endswith("+"):
            start_rev = start[:-1]+"-"
        else:
            start_rev = start[:-1]+"+"

        end = segments[1]
        end_rev = ""

        if end.endswith("+"):
            end_rev = end[:-1]+"-"
        else:
            end_rev = end[:-1]+"+"

        new_links = []

        if start in links_map:
            new_links.extend(list(links_map[start]))
        if start_rev in links_map:
            new_links.extend(list(links_map[start_rev]))
        if end in links_map:
            new_links.extend(list(links_map[end]))
        if end_rev in links_map:
            new_links.extend(list(links_map[end_rev]))

        for new_link in new_links:
            if new_link in segment_contigs:
                for contig in segment_contigs[new_link]:
                    if i!=int(contig):
                        # Add edge to list of edges
                        edge_list.append((i,contigs_map_rev[int(contig)]))

    # Add edges to the graph
    assembly_graph.add_edges(edge_list)
    assembly_graph.simplify(multiple=True, loops=False, combine_edges=None)

except:
    logger.error("Please make sure that the correct path to the assembly graph file is provided.")
    logger.info("Exiting GraphBin2... Bye...!")
    sys.exit(1)

logger.info("Total number of edges in the assembly graph: "+str(len(edge_list)))


# Get the number of bins from the initial binning result
#--------------------------------------------------------

try:
    all_bins_list = []

    with open(contig_bins_file) as csvfile:
        readCSV = csv.reader(csvfile, delimiter=delimiter)
        for row in readCSV:
            all_bins_list.append(row[1])

    bins_list = list(set(all_bins_list))
    bins_list.sort()

    n_bins = len(bins_list)
    logger.info("Number of bins available in binning result: "+str(n_bins))
except:
    logger.error("Please make sure that the correct path to the binning result file is provided and it is having the correct format")
    logger.info("Exiting GraphBin2... Bye...!")
    sys.exit(1)


if gold_standard != "":
    gsdf = pd.read_csv(gold_standard, sep=delimiter, names=['SEQUENCEID', 'BINID', 'LENGTH'])
    df = pd.read_csv(contig_bins_file, sep=delimiter, names=['SEQUENCEID', 'BINID'])
    abundant_genome_dict = most_abundant_bins(gsdf, df)
    gs_seq_dict_temp = pd.Series((str(x) for x in gsdf['BINID']), index=gsdf['SEQUENCEID']).to_dict()
    # logger.info(gs_seq_dict_temp)
    gs_seq_dict = {}
    # logger.info(gs_seq_dict_temp)
    start = 'NODE_'
    end = '_length_'
    for k in gs_seq_dict_temp.keys():
        if gs_seq_dict_temp[k] in abundant_genome_dict.keys():
            contig_num = contigs_map_rev[int(re.search('%s(.*)%s' % (start, end), str(k)).group(1))]
            gs_seq_dict[contig_num] = int(abundant_genome_dict[gs_seq_dict_temp[k]]) - 1
    # logger.info(len(abundant_genome_dict))
    # logger.info(gs_seq_dict)
    # exit(1)
    logger.info(f'gs_seq_dict size: {len(gs_seq_dict)}')
    logger.info('GOT DICT FOR ABUNDANT GENOMES')



# Get initial binning result
#----------------------------

pred_contigs_to_bin = {}
bins = [[] for x in range(n_bins)]
bins_allowed = set()
if gold_standard != "":
    for cn in gs_seq_dict.keys():
        bins_allowed.add(gs_seq_dict[cn])
try:
    with open(contig_bins_file) as contig_bins:
        readCSV = csv.reader(contig_bins, delimiter=delimiter)
        for row in readCSV:
            # row[0] += '_length_'
            start = 'NODE_'
            end = '_length_'
            contig_num = contigs_map_rev[int(re.search('%s(.*)%s' % (start, end), row[0]).group(1))]

            bin_num = int(row[1])-1
            pred_contigs_to_bin[contig_num] = bin_num
            bins[bin_num].append(contig_num)

except:
    logger.error("Please make sure that you have provided the correct assembler type and the correct path to the binning result file in the correct format.")
    logger.info("Exiting GraphBin2... Bye...!")
    sys.exit(1)


# Get binned and unbinned contigs
#-----------------------------------------------------

binned_contigs = []

for n in range(n_bins):
    binned_contigs = sorted(binned_contigs+bins[n])

unbinned_contigs = []

for i in range(node_count):
    if i not in binned_contigs:
        unbinned_contigs.append(i)

binned_contigs.sort()
unbinned_contigs.sort()

logger.info("Number of binned contigs: "+str(len(binned_contigs)))
logger.info("Total number of unbinned contigs: "+str(len(unbinned_contigs)))


# Get isolated vertices
#-----------------------------------------------------

isolated=[]

for i in range(node_count):

    neighbours = assembly_graph.neighbors(i, mode=ALL)

    if len(neighbours)==0:
        isolated.append(i)

logger.info("Number of isolated contigs: "+str(len(isolated)))


# The BFS function to search labelled nodes
#-----------------------------------------------------

def runBFS(node, threhold=depth, add_depth=0):
    queue = []
    visited = set()
    queue.append(node)
    depth = {}

    depth[node] = 0

    labelled_nodes = set()

    while (len(queue) > 0):
        active_node = queue.pop(0)
        visited.add(active_node)

        if active_node in binned_contigs and len(visited) > 1:

            contig_bin = -1

            # Get the bin of the current contig
            for n in range(n_bins):
                if active_node in bins[n]:
                    contig_bin = n
                    break

            labelled_nodes.add((node, active_node, contig_bin, depth[active_node], abs(coverages[contigs_map[node]]-coverages[contigs_map[active_node]])))

        else:
            for neighbour in assembly_graph.neighbors(active_node, mode=ALL):
                if neighbour not in visited:

                    # Code segment for propagation of true labels
                    if gold_standard != "" and add_depth > 0 \
                            and neighbour in gs_seq_dict.keys():

                        if neighbour in unbinned_contigs:
                            binned_contigs.append(neighbour)
                            unbinned_contigs.remove(neighbour)
                        elif neighbour in binned_contigs:
                            for i in range(n_bins):
                                if neighbour in bins[i]:
                                    bins[i].remove(neighbour)

                        bins[gs_seq_dict[neighbour]].append(neighbour)
                    depth[neighbour] = depth[active_node] + 1
                    if depth[neighbour] > threhold:
                        continue
                    queue.append(neighbour)
            add_depth -=1


    return labelled_nodes


if add_true_depth > 0:
    for contig in binned_contigs:
        _ = runBFS(contig, threhold=depth, add_depth=add_true_depth)


graph_depth_counter = defaultdict(lambda: defaultdict(int))

for contig in binned_contigs:
    contig_info = runBFS(contig, threhold=depth)
    for node in contig_info:
        if node[3] <= depth and node[3] != 0:
            graph_depth_counter[contig][node[3]] += 1

depth_map_before_init = defaultdict(lambda: defaultdict(int))
for contig in binned_contigs:
    contig_info = runBFS(contig, threhold=depth)
    for node in contig_info:
        if contig not in gs_seq_dict.keys():
            break
        if node[1] not in gs_seq_dict.keys():
            continue
        if node[3] <= depth and node[3] != 0:
            depth_map_before_init[contig][node[3]] +=1/graph_depth_counter[contig][node[3]] if  \
                gs_seq_dict[contig] == gs_seq_dict[node[1]] else 0

list_of_lists = []

for k, v in depth_map_before_init.items():
    _ = [contigs_map[k]]
    t__ = [0] * depth
    for k_1, v_1 in v.items():
        t__[k_1 - 1] = round(v_1,2) if v_1 != 0 else 0
    _ += t__
    list_of_lists.append(_)

df = pd.DataFrame(list_of_lists, columns=['contig_num'] + ['depth' + str(k+1) for k in range(depth)])
df.to_csv(output_path + 'depth_map_before_init.csv', index=False, sep='\t')


if add_true_depth > 0:
    write_bins(bins, contig_names, output_path + prefix + "bfs_res.csv")

# Remove labels of unsupported vertices
#-----------------------------------------------------

logger.info("Removing labels of unsupported vertices")

iter_num = 1


while True:

    logger.debug("Iteration: "+str(iter_num))

    remove_labels = {}

    # Initialise progress bar
    pbar = tqdm(total=len(binned_contigs))

    for my_node in binned_contigs:

        if my_node not in isolated:

            my_contig_bin = -1

            # Get the bin of the current contig
            for n in range(n_bins):
                if my_node in bins[n]:
                    my_contig_bin = n
                    break

            BFS_labelled_nodes = list(runBFS(my_node))

            if len(BFS_labelled_nodes)>0:

                # Get the count of nodes in the closest_neighbours that belongs to each bin
                BFS_labelled_bin_counts = [0 for x in range(n_bins)]

                for i in range(len(BFS_labelled_nodes)):
                    BFS_labelled_bin_counts[BFS_labelled_nodes[i][2]] += 1

                zero_bin_count = 0

                # Count the number of bins which have no BFS_labelled_contigs
                for j in BFS_labelled_bin_counts:
                    if j == 0:
                        zero_bin_count += 1

                # Get the bin number which contains the maximum number of BFS_labelled_contigs
                max_index = BFS_labelled_bin_counts.index(max(BFS_labelled_bin_counts))

                # If there are no BFS nodes of same label as contig, remove label
                if my_contig_bin!=-1 and BFS_labelled_bin_counts[my_contig_bin]==0:
                    remove_labels[my_node] = my_contig_bin

                # Check if all the BFS_labelled_contigs are in one bin
                elif zero_bin_count == (len(BFS_labelled_bin_counts)-1):

                    # If contig is not in the bin with maximum number of BFS_labelled_contigs
                    if max_index!=my_contig_bin and BFS_labelled_bin_counts[max_index] > 1 and contig_lengths[contigs_map[my_node]]<10000:
                        remove_labels[my_node] = my_contig_bin

        # Update progress bar
        pbar.update(1)

    # Close progress bar
    pbar.close()


    if len(remove_labels)==0:
        break
    else:

        for contig in remove_labels:
            bins[remove_labels[contig]].remove(contig)
            binned_contigs.remove(contig)
            unbinned_contigs.append(contig)

    iter_num += 1

if save_interval:   #####
    write_bins(bins, contigs_map, output_path + prefix + "after_removal.csv" )


# Refine labels of inconsistent vertices
#-----------------------------------------------------
if not skip_ref:  #####
    print("\nRefining labels of inconsistent vertices...")

    iter_num = 1

    once_moved = []

    while True:

        print("Iteration:", iter_num)

        contigs_to_correct = {}

        # Initialise progress bar
        pbar = tqdm(total=len(binned_contigs))

        for my_node in binned_contigs:

            if my_node not in isolated and my_node not in once_moved:

                my_contig_bin = -1

                # Get the bin of the current contig
                for n in range(n_bins):
                    if my_node in bins[n]:
                        my_contig_bin = n
                        break

                BFS_labelled_nodes = list(runBFS(my_node))

                # Get the count of nodes in the closest_neighbours that belongs to each bin
                BFS_labelled_bin_counts = [0 for x in range(n_bins)]

                for i in range(len(BFS_labelled_nodes)):
                    BFS_labelled_bin_counts[BFS_labelled_nodes[i][2]] += 1

                zero_bin_count = 0

                # Count the number of bins which have no BFS_labelled_contigs
                for j in BFS_labelled_bin_counts:
                    if j == 0:
                        zero_bin_count += 1

                # Get the bin number which contains the maximum number of BFS_labelled_contigs
                max_index = BFS_labelled_bin_counts.index(max(BFS_labelled_bin_counts))

                weighted_bin_count = [0 for x in range(n_bins)]

                for i in range(len(BFS_labelled_nodes)):

                    path_length = BFS_labelled_nodes[i][3]
                    weighted_bin_count[BFS_labelled_nodes[i][2]] += 1/(2**path_length)

                should_move = False

                max_weight = -1
                max_weight_bin = -1

                for i in range(len(weighted_bin_count)):
                    if len(BFS_labelled_nodes)>0 and my_contig_bin!=-1 and i!=my_contig_bin and weighted_bin_count[i]>0 and weighted_bin_count[i] > weighted_bin_count[my_contig_bin]*threshold:
                        should_move = True
                        if max_weight < weighted_bin_count[i]:
                            max_weight = weighted_bin_count[i]
                            max_weight_bin = i

                if should_move and max_weight_bin!=-1:
                    contigs_to_correct[my_node] = (my_contig_bin, max_weight_bin)
                    once_moved.append(my_node)

            # Update progress bar
            pbar.update(1)

        # Close progress bar
        pbar.close()

        if len(contigs_to_correct)==0:
            break
        else:
            for contig in contigs_to_correct:
                old_bin = contigs_to_correct[contig][0]
                new_bin = contigs_to_correct[contig][1]
                bins[old_bin].remove(contig)
                bins[new_bin].append(contig)
                bins[new_bin].sort()

        iter_num += 1

if save_interval:   #####
    write_bins(bins, contigs_map, output_path + prefix + f"propagation_0.csv")

# Get non isolated contigs

logger.info("Obtaining non isolated contigs")

# Initialise progress bar
pbar = tqdm(total=node_count)

non_isolated = []

for i in range(node_count):

    if i not in non_isolated and i in binned_contigs:

        component = []
        component.append(i)
        length = len(component)
        neighbours = assembly_graph.neighbors(i, mode=ALL)

        for neighbor in neighbours:

            if neighbor not in component:
                component.append(neighbor)

        component = list(set(component))

        while length!= len(component):

            length = len(component)

            for j in component:

                neighbours = assembly_graph.neighbors(j, mode=ALL)

                for neighbor in neighbours:
                    if neighbor not in component:
                        component.append(neighbor)

        labelled = False
        for j in component:
            if j in binned_contigs:
                labelled = True
                break

        if labelled:
            for j in component:
                if j not in non_isolated:
                    non_isolated.append(j)

    # Update progress bar
    pbar.update(1)

# Close progress bar
pbar.close()


# Propagating true labels
if add_true_depth > 0:
    for contig in binned_contigs:
        if contig not in isolated:
            _ = runBFS(contig, threhold=depth)

logger.info("Number of non-isolated contigs: "+str(len(non_isolated)))

non_isolated_unbinned = list(set(non_isolated).intersection(set(unbinned_contigs)))

logger.info("Number of non-isolated unbinned contigs: "+str(len(non_isolated_unbinned)))


write_bins(bins, contig_names, output_path + prefix + "stage_2.csv")


# Propagate labels to unlabelled vertices
#-----------------------------------------------------

logger.info("Propagating labels to unlabelled vertices")

# Initialise progress bar
pbar = tqdm(total=len(non_isolated_unbinned))

class DataWrap:
    def __init__(self, data):
        self.data = data

    def __lt__(self, other):
        return (self.data[3], self.data[-1])  < (other.data[3], other.data[-1])

contigs_to_bin = set()

for contig in binned_contigs:
    if contig in non_isolated:
        closest_neighbours = filter(lambda x: x not in binned_contigs, assembly_graph.neighbors(contig, mode=ALL))
        contigs_to_bin.update(closest_neighbours)


sorted_node_list = []
sorted_node_list_ = [list(runBFS(x, threhold=depth)) for x in contigs_to_bin]
sorted_node_list_ = [item for sublist in sorted_node_list_ for item in sublist]

for data in sorted_node_list_:
    heapObj = DataWrap(data)
    heapq.heappush(sorted_node_list, heapObj)

prop_iter = 1
while sorted_node_list:
    if save_interval != 0 and save_heap and prop_iter % save_interval == 0:    #####
        write_heap(deepcopy(sorted_node_list), contigs_map, f"heap_{prop_iter}.tsv")

    # Pop items from heap until contig that satisfies thresholds is picked. If heap becomes empty propagation ends.
    while sorted_node_list:  #####
        best_choice = heapq.heappop(sorted_node_list)
        to_bin, binned, bin_, dist, cov_diff = best_choice.data
        good_contig = coverages[contigs_map[to_bin]] >= cov_threshold and \
                      contig_lengths[contigs_map[to_bin]] >= len_threshold
        if good_contig:
            break
    else:
        break

    if to_bin in non_isolated_unbinned:
        bins[bin_].append(to_bin)
        binned_contigs.append(to_bin)
        non_isolated_unbinned.remove(to_bin)
        unbinned_contigs.remove(to_bin)

        # Update progress bar
        pbar.update(1)

        # Discover to_bin's neighbours
        unbinned_neighbours = set(filter(lambda x: x not in binned_contigs, assembly_graph.neighbors(to_bin, mode=ALL)))
        sorted_node_list = list(filter(lambda x: x.data[0] not in unbinned_neighbours, sorted_node_list))
        heapq.heapify(sorted_node_list)

        for n in unbinned_neighbours:
            candidates = list(runBFS(n, threhold=depth))
            for c in candidates:
                heapq.heappush(sorted_node_list, DataWrap(c))
    if save_interval != 0 and prop_iter % save_interval == 0:    #####
        write_bins(bins, contigs_map, output_path + prefix + f"propagation_{prop_iter}.csv")
    prop_iter += 1

# Close progress bar
pbar.close()

# Determine contigs belonging to multiple bins
#-----------------------------------------------------

logger.info("Determining multi-binned contigs")

bin_cov_sum = [0 for x in range(n_bins)]
bin_contig_len_total = [0 for x in range(n_bins)]

for i in range(n_bins):
    for j in range(len(bins[i])):
        if bins[i][j] in non_isolated:
            bin_cov_sum[i] += coverages[contigs_map[bins[i][j]]]*contig_lengths[contigs_map[bins[i][j]]]
            bin_contig_len_total[i] += contig_lengths[contigs_map[bins[i][j]]]

def is_multi(contig):
    if contig in non_isolated and contig in binned_contigs:

        contig_bin = -1

        # Get the bin of the current contig
        for n in range(n_bins):
            if contig in bins[n]:
                contig_bin = n
                break

        # Get average coverage of each connected component representing a bin excluding the contig
        bin_coverages = list(bin_cov_sum)
        bin_contig_lengths = list(bin_contig_len_total)

        bin_coverages[contig_bin] = bin_coverages[contig_bin] - (coverages[contigs_map[contig]]*contig_lengths[contigs_map[contig]])
        bin_contig_lengths[contig_bin] = bin_contig_lengths[contig_bin] - contig_lengths[contigs_map[contig]]

        for i in range(n_bins):
            if bin_contig_lengths[i] != 0:
                bin_coverages[i] = bin_coverages[i]/bin_contig_lengths[i]

        # Get coverages of neighbours
        neighbour_bins = [[] for x in range(n_bins)]

        neighbour_bin_coverages = [[] for x in range(n_bins)]

        neighbours = assembly_graph.neighbors(contig, mode=ALL)

        for neighbour in neighbours:

            for n in range(n_bins):
                if neighbour in bins[n]:
                    neighbour_bins[n].append(neighbour)
                    neighbour_bin_coverages[n].append(coverages[contigs_map[neighbour]])
                    break

        zero_bin_count = 0

        non_zero_bins = []

        # Count the number of bins which have no labelled neighbouring contigs
        for i in range(len(neighbour_bins)):
            if len(neighbour_bins[i]) == 0:
                zero_bin_count += 1
            else:
                non_zero_bins.append(i)

        if zero_bin_count < n_bins-1:

            bin_combinations = []

            for i in range(len(non_zero_bins)):
                bin_combinations += list(it.combinations(non_zero_bins, i+1))

            min_diff = sys.maxsize
            min_diff_combination = -1

            for combination in bin_combinations:

                comb_cov_total = 0

                for i in range(len(combination)):
                    comb_cov_total += bin_coverages[combination[i]]

                cov_diff = abs(comb_cov_total-coverages[contigs_map[contig]])

                if cov_diff < min_diff:
                    min_diff = cov_diff
                    min_diff_combination = combination

            if min_diff_combination!=-1 and len(min_diff_combination) > 1 and contig_lengths[contigs_map[contig]]>1000:
                # return True
                return contig, min_diff_combination

    return None

contigs_to_propagated = {}
for i in range(n_bins):
    for contig in bins[i]:
        contigs_to_propagated[contig] = i

graph_depth_counter = defaultdict(lambda: defaultdict(int))

for contig in binned_contigs:
    contig_info = runBFS(contig, threhold=depth)
    for node in contig_info:
        if node[3] <= depth and node[3] != 0:
            graph_depth_counter[contig][node[3]] += 1


depth_map_after_propag = defaultdict(lambda: defaultdict(int))
for contig in binned_contigs:
    contig_info = runBFS(contig, threhold=depth)
    for node in contig_info:
        if contig not in gs_seq_dict.keys():
            break
        if node[1] not in contigs_to_propagated.keys():
            continue
        if node[3] <= depth and node[3] != 0 and graph_depth_counter[contig][node[3]] != 0:
            depth_map_after_propag[contig][node[3]] += 1 / graph_depth_counter[contig][node[3]] if \
                gs_seq_dict[contig] == contigs_to_propagated[node[1]] else 0

list_of_lists = []

for k, v in depth_map_after_propag.items():
    _ = [contigs_map[k]]
    t__ = [0] * depth
    for k_1, v_1 in v.items():
        t__[k_1 - 1] = round(v_1,2) if v_1 != 0 else 0
    _ += t__
    list_of_lists.append(_)

df = pd.DataFrame(list_of_lists, columns=['contig_num'] + ['depth' + str(k+1) for k in range(depth)])
df.to_csv(output_path + 'depth_map_after_propagation.csv', index=False, sep='\t')

# Threads and multi-processing
with Pool(nthreads) as p:
    mapped = list(tqdm(p.imap(is_multi, list(range(node_count))), total=node_count))

multi_bins = list(filter(lambda x: x is not None, mapped))

if len(multi_bins) == 0:
    logger.info("No multi-labelled contigs were found ==>")
else:
    logger.info("Found "+str(len(multi_bins))+" multi-labelled contigs")

# Add contigs to multiplt bins
for contig, min_diff_combination in multi_bins:
    logger.info(contig_names[contig]+" belongs to bins "+', '.join(str(s+1) for s in min_diff_combination))
    for mybin in min_diff_combination:
        if contig not in bins[mybin]:
            bins[mybin].append(contig)


# Determine elapsed time
elapsed_time = time.time() - start_time

# Show elapsed time for the process
logger.info("Elapsed time: "+str(elapsed_time)+" seconds")

# Sort contigs in bins
for i in range(n_bins):
    bins[i].sort()


# Write result to output file
#-----------------------------------

logger.info("Writing the final binning results to file")

output_bins = []

for i in range(node_count):
    for k in range(n_bins):
        if i in bins[k]:
            line = []
            line.append(contig_names[i])
            line.append(k+1)
            output_bins.append(line)

output_file = output_path + prefix + 'graphbin2_output.csv'

with open(output_file, mode='w') as output_file:
    output_writer = csv.writer(output_file, delimiter=delimiter, quotechar='"', quoting=csv.QUOTE_MINIMAL)

    for row in output_bins:
        output_writer.writerow(row)

logger.info("Final binning results can be found at "+str(output_file.name))


# Exit program
#-----------------------------------

logger.info("Thank you for using GraphBin2!")