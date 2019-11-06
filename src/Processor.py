import os
import multiprocessing
from Clusterer import Clusterer
from ClusterMerge import ClusterMerge
from FileSegmentReader import FileSegmentReader
from MapReduce import MapReduce
from Segmentator import Segmentator


FIXED_MAP_JOB_KEY = 1  # Single key for the whole map-reduce operation


class Processor():
    def __init__(self, config, cluster_config):
        self.cluster_config = cluster_config
        self.segmentator = Segmentator(multiprocessing.cpu_count())
        self.config = config

    def process(self, filenames):
        if self.config.get('single_core'):
            return self.process_single_core(filenames)
        else:
            return self.process_multi_cores(filenames)

    def process_multi_cores(self, filenames):
        """
        Process the file in parallel with multiple processes.

        This is a little bit different than the approach described in the
        LogMine paper. Each "map job" is a chunk of multiple lines (instead of
        a single line), this helps utilizing multiprocessing better.

        Do note that this method may return different result in each run, and
        different with the other version "process_single_core". This is
        expected, as the result depends on the processing order - which is
        not guaranteed when tasks are performed in parallel.
        """
        segments = self.segmentator.create_segments(filenames)

        # Perform clustering all chunks in parallel
        mapper = MapReduce(
            map_segments_to_clusters,
            reduce_clusters,
            params=self.cluster_config
        )
        result = mapper(segments)

        if len(result) == 0:
            return []

        (key, clusters) = result[0]
        return clusters

    def process_single_core(self, filenames):
        """
        Process the file sequencially using 1 a single processor
        """
        clusterer = Clusterer(**self.cluster_config)
        for filename in filenames:
            with open(filename, 'r') as f:
                for line in f:
                    clusterer.process_line(line)
        return clusterer.result()

# The methods below are used by multiprocessing.Pool and need to be defined at
# top level


def map_segments_to_clusters(x):
    # print('mapper: %s working on %s' % (os.getpid(), x))
    ((filename, start, end, size), config) = x
    clusterer = Clusterer(**config)
    lines = FileSegmentReader.read(filename, start, end, size)
    clusters = clusterer.find(lines)
    return [(FIXED_MAP_JOB_KEY, clusters)]


def reduce_clusters(x):
    """
    Because all map job have the same key, this reduce operation will be
    executed in one single processor. Most of the time, the number of clusters
    in this step is small so it is kind of acceptable.
    """
    # print('reducer: %s working on %s items' % (os.getpid(), len(x[0][1])))
    # a = [debug_print(i) for i in x[0][1]]
    ((key, clusters_groups), config) = x
    if len(clusters_groups) <= 1:
        return (key, clusters_groups)  # Nothing to merge

    base_clusters = clusters_groups[0]
    merger = ClusterMerge(config)
    for clusters in clusters_groups[1:]:
        # print('merging %s-%s' % (len(base_clusters), len(clusters)))
        merger.merge(base_clusters, clusters)
    return (key, base_clusters)