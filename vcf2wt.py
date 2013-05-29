#!python
"""
VCF processing for wormtable. 

TODO:document.

Implementation Note: We use bytes throughout the parsing process here for
a few reasons. Mostly, this is because it's much easier to deal with bytes
values within the C module, as we'd have to decode Unicode objects before 
getting string. At the same time, it's probably quite a bit more efficient 
to work with bytes directly, so we win both ways. It's a bit tedious making 
sure that all the literals have a 'b' in front of them, but worth the 
effort.

"""
from __future__ import print_function
from __future__ import division 

import os
import sys
import argparse
import shutil 
import gzip

import wormtable as wt

# VCF Fixed columns

CHROM = b"CHROM"
POS = b"POS"
ID = b"ID"
REF = b"REF"
ALT = b"ALT"
QUAL = b"QUAL"
FILTER = b"FILTER"
INFO = b"INFO"

# TODO put in proper descriptions
CHROM_DESCRIPTION = b"CHROM"
POS_DESCRIPTION = b"POS"
ID_DESCRIPTION = b"ID"
REF_DESCRIPTION = b"REF"
ALT_DESCRIPTION = b"ALT"
QUAL_DESCRIPTION = b"QUAL"
FILTER_DESCRIPTION = b"FILTER"
INFO_DESCRIPTION = b"INFO"

# Special values in VCF
MISSING_VALUE = b"."

# Strings used in the header for identifiers
ID = b"ID"
DESCRIPTION = b"Description"
NUMBER = b"Number"
TYPE = b"Type"
INTEGER = b"Integer"
FLOAT = b"Float"
FLAG = b"Flag"
CHARACTER = b"Character"
STRING = b"String"

def open_file(vcf_file):
    """
    Opens the specified VCF file and returns two file objects: one ready 
    for reading, and the other indicating the position in the underlying 
    file. If compression is not used, these are the same. Only the 
    reading_file should be closed at the end of the process.
    """
    if vcf_file.endswith(".gz"):
        reading_file = gzip.open(vcf_file, "rb")
        progress_file = reading_file.fileobj
    else:
        reading_file = open(vcf_file, "rb")
        progress_file = reading_file
    return reading_file, progress_file


class VCFTableBuilder(object):
    """
    Class responsible for parsing a VCF file and creating a database. 
    """
    def __init__(self, homedir, vcf_file):
        self.__table = wt.Table(homedir) 
        self.__source_path = vcf_file 
        self.__progress_update_rows = 0 
        self.__progress_monitor = None
        self.__progress_file = None
        self.__source_file = None

    def set_progress_monitoring(self, monitor):
        """
        If monitor is True, activate progress monitoring; otherwise, leave
        progress monitoring deactivated.
        """
        if monitor:
            file_size = os.path.getsize(self.__source_path) 
            self.__progress_monitor = wt.ProgressMonitor(file_size, "bytes")

    def set_progress_update_rows(self, progress_update_rows):
        """
        Sets the number of rows that we update progress at to the specified 
        value.
        """
        self.__progress_update_rows = progress_update_rows

    def update_progress(self):
        """
        Reads the position we are at in the underlying file and uses this to 
        update the progress bar, if used.
        """
        if self.__progress_monitor is not None:
            t = self.__progress_file.tell() 
            self.__progress_monitor.update(t)

    def build(self):
        """
        Builds the table.
        """
        reading_file, progress_file = open_file(vcf_file)
        self.__source_file = reading_file 
        self.__progress_file = progress_file
        
        self._prepare()
        self._insert_rows()
        self.close_database()
        self.finalise()
        reading_file.close()
        if progress_monitor:
            self._progress_monitor.update(file_size)
            self._progress_monitor.finish()

   
    def _prepare(self):
        """
        Prepares for parsing records by getting the database columns 
        ready and skipping the file header.
        """
        f = self._source_file
        # Skip the header
        s = f.readline()
        while s.startswith(b"##"):
            s = f.readline()
        # Get the genotypes from the header
        genotypes = s.split()[9:] 
        # In the interest of efficiency, we want to split the columns 
        # up into the smallest possible lists so we don't have to 
        # put in as much effort searching for them.
        all_columns = dict((c.name, c) for c in self._schema.get_columns())
        all_fixed_columns = [CHROM, POS, ID, REF, ALT, QUAL, FILTER]
        self._fixed_columns = []
        for j in range(len(all_fixed_columns)):
            name = all_fixed_columns[j]
            if name in all_columns:
                self._fixed_columns.append((all_columns[name], j))
        self._info_columns = {}
        self._genotype_columns = [{} for g in genotypes]
        for c in self._schema.get_columns()[1:]:
            if b"_" in c.name:
                split = c.name.split(b"_")
                if split[0] == INFO:
                    name = split[1]
                    self._info_columns[name] = c
                else:
                    g = b"_".join(split[:-1])
                    name = split[-1]
                    index = genotypes.index(g)
                    self._genotype_columns[index][name] = c
    

    def _insert_elements(self, col, encoded):
        """
        Insert the elements into the table after converting to the correct
        types.
        
        This should be redundant if we're using the C based parsing of encoded
        elements.
        """
        col_position = col.position 
        rb = self._row_buffer
        if col.element_type == wt.WT_CHAR:
            rb.insert_elements(col_position, encoded)
        else:
            f = int
            if col.element_type == wt.WT_FLOAT:
                f = float
            if col.num_elements == 1:
                rb.insert_elements(col_position, f(encoded))
            else:
                l = [f(s) for s in encoded.split(b",")]
                rb.insert_elements(col_position, l)
                    
                

    def _insert_rows(self):
        """
        Builds the database in opened file.
        """
        fixed_columns = self._fixed_columns
        info_columns = self._info_columns
        genotype_columns = self._genotype_columns
        t = self._row_buffer
        num_rows = 0
        for s in self._source_file:
            l = s.split()
            # Read in the fixed columns
            for col, index in fixed_columns:
                if l[index] != MISSING_VALUE:
                    t.insert_encoded_elements(col.position, l[index])
                    #self._insert_elements(col, l[index])
            # Now process the info columns.
            for mapping in l[7].split(b";"):
                tokens = mapping.split(b"=")
                name = tokens[0]
                if name in info_columns:
                    col = info_columns[name]
                    if len(tokens) == 2:
                        t.insert_encoded_elements(col.position, tokens[1])
                        #self._insert_elements(col, tokens[1])
                    else:
                        # This is a Flag column.
                        t.insert_elements(col.position, [1])
            # Process the genotype columns. 
            j = 0
            fmt = l[8].split(b":")
            for genotype_values in l[9:]:
                tokens = genotype_values.split(b":")
                if len(tokens) == len(fmt):
                    for k in range(len(fmt)):
                        if fmt[k] in genotype_columns[j]:
                            col = genotype_columns[j][fmt[k]]
                            t.insert_encoded_elements(col.position, tokens[k])
                            #self._insert_elements(col, tokens[k])
                elif len(tokens) > 1:
                    # We can treat a genotype value on its own as missing values.
                    # We can have skipped columns at the end though, which we 
                    # should deal with properly. So, put in a loud complaint 
                    # here and fix later.
                    print("PARSING CORNER CASE NOT HANDLED!!! FIXME!!!!")
                j += 1
            # Finally, commit the record.
            self._row_buffer.commit_row()
            num_rows += 1
            if num_rows % self._progress_update_rows == 0:
                self._update_progress()

####### Command line interface ###############

def oldmain():
    usage = "usage: %prog [options] vcf-file homedir"
    parser = optparse.OptionParser(usage=usage) 
    parser.add_option("-f", "--force", dest="force",
            action="store_true", default=False,
            help="overwrite existing wormtable", metavar="FORCE")
    parser.add_option("-p", "--progress", dest="progress",
            action="store_true", default=False,
            help="show progress monitor", metavar="PROGRESS")
    parser.add_option("-c", "--cache-size", dest="cache_size",
            help="cache size in K, M or G", default="64M")
    parser.add_option("-s", "--schema", dest="schema",
            help="user-specified schema for table", default=None)
    parser.add_option("-g", "--generate-schema", dest="generate_schema",
            help="generate the schema, write to stdout and quit. "
                "Use in conjunction with -s,", action="store_true", 
                default=False)
    (options, args) = parser.parse_args()
    if len(args) != 1:
        parser.error("Incorrect number of arguments")
    vcf_file = args[0]
    if options.generate_schema:
        print("generating schema for ", vcf_file) 
        t = VCFTable(vcf_file)
        t.read_header() 

    #homedir = args[1]
    #if os.path.exists(homedir):
    #    if options.force:
    #        shutil.rmtree(homedir)
    #    else:
    #        s = "Directory '{0}' exists: use -f to overwrite".format(homedir)
    #        parser.error(s)
    #os.mkdir(homedir)
    
    

    # input_schema = os.path.join(homedir, "schema.xml")
    # schema = vcf_schema_factory(vcf_file)
    
    #schema.write_xml(input_schema)
    #dbb = VCFTableBuilder(homedir, input_schema)
    #dbb.set_cache_size(cache_size)
    #tb = VCFTableBuilder(homedir, vcf_file)
    # we want fluid progress for small files and to not
    # waste time for large files.
    #progress_rows = 100
    #statinfo = os.stat(vcf_file)
    #if statinfo.st_size > 2**30:
    #    progress_rows = 10000
    #tb.set_progress_monitoring(options.progress)
    #tb.set_progress_update_rows(progress_rows)
    #tb.set_cache_size(options.cache_size)
    #tb.build()
### New implementation ##############################################


class VCFParser(object):
    """
    A class representing a VCF file parser.
    """
    def __init__(self, input_file):
        self.__input_file = input_file
        self.__genotypes = []

    def parse_version(self, s):
        """
        Parse the VCF version number from the specified string.
        """
        self._version = -1.0
        tokens = s.split(b"v")
        if len(tokens) == 2:
            self._version = float(tokens[1])

    def parse_header_line(self, s):
        """
        Processes the specified header string to get the genotype labels.
        """
        self.__genotypes = s.split()[9:]

    def add_column(self, table, prefix, line):
        """
        Adds a VCF column using the specified metadata line with the specified 
        name prefix to the specified table.
        """
        d = {}
        s = line[line.find(b"<") + 1: line.find(b">")]
        for j in range(3):
            k = s.find(b",")
            tokens = s[:k].split(b"=")
            s = s[k + 1:]
            d[tokens[0]] = tokens[1]
        tokens = s.split(b"=", 1)
        d[tokens[0]] = tokens[1]
        name = d[ID]
        description = d[DESCRIPTION].strip(b"\"")
        number = d[NUMBER]
        num_elements = wt.WT_VARIABLE 
        try:
            # If we can parse it into a number, do so. If this fails than use
            # a variable number of elements.
            num_elements = int(number)    
        except ValueError as v:
            pass
        # We can also have negative num_elements to indicate variable column
        if num_elements < 0:
            num_elements = wt.WT_VARIABLE 
        st = d[TYPE]
        if st == INTEGER:
            element_type = wt.WT_INT
            element_size = 4
        elif st == FLOAT: 
            element_type = wt.WT_FLOAT
            element_size = 4
        elif st == FLAG: 
            element_type = wt.WT_INT
            element_size = 1
        elif st == CHARACTER: 
            element_type = wt.WT_CHAR
            element_size = 1
        elif st == STRING: 
            num_elements = wt.WT_VARIABLE 
            element_type = wt.WT_CHAR
            element_size = 1
        else:
            raise ValueError("Unknown VCF type:", st)
        
        table.add_column(prefix + b"_" + name,  description, element_type, 
                element_size, num_elements)

    def generate_schema(self, table):
        """
        Reads the header from the specified VCF file and returns a Table 
        with the correct columns.
        """
        f = self.__input_file
        s = f.readline()
        info_descriptions = []
        genotype_descriptions = []
        self.parse_version(s)
        if self._version < 4.0:
            raise ValueError("VCF versions < 4.0 not supported")
        while s.startswith(b"##"):
            # skip FILTER values 
            if s.startswith(b"##INFO"):
                info_descriptions.append(s)
            elif s.startswith(b"##FORMAT"):
                genotype_descriptions.append(s)
            s = f.readline()
        self.parse_header_line(s)
        # Add the fixed columns
        table.add_id_column(5)
        table.add_char_column(CHROM, CHROM_DESCRIPTION)
        table.add_uint_column(POS, POS_DESCRIPTION, 5)
        table.add_char_column(ID, ID_DESCRIPTION)
        table.add_char_column(REF, REF_DESCRIPTION)
        table.add_char_column(ALT, ALT_DESCRIPTION)
        table.add_float_column(QUAL, QUAL_DESCRIPTION, 4)
        table.add_char_column(FILTER, FILTER_DESCRIPTION)
        for s in info_descriptions:
            self.add_column(table, INFO, s)
        for genotype in self.__genotypes:
            for s in genotype_descriptions: 
                self.add_column(table, genotype, s) 

    def rows(self, table_columns):
        """
        Returns an iterator over the rows in this VCF file. Each row is a 
        dictionary mapping column positions to their encoded string values.
        """
        # First we construct the mappings from the various parts of the 
        # VCF row to the corresponding column index in the wormtable
        num_columns = len(table_columns) 
        all_fixed_columns = [CHROM, POS, ID, REF, ALT, QUAL, FILTER]
        fixed_columns = []
        # weed out the columns that are not in the table
        for j in range(len(all_fixed_columns)):
            name = all_fixed_columns[j]
            if name in table_columns:
                fixed_columns.append((j, table_columns[name]))
        info_columns = {}
        genotype_columns = [{} for g in self.__genotypes]
        for k, v in table_columns.items(): 
            if b"_" in k and v != 0:
                split = k.split(b"_")
                if split[0] == INFO:
                    name = split[1]
                    info_columns[name] = v 
                else:
                    g = b"_".join(split[:-1])
                    name = split[-1]
                    index = self.__genotypes.index(g)
                    genotype_columns[index][name] = v 
        # Now we are ready to process the file.
        for s in self.__input_file:
            row = [None for j in range(num_columns)] 
            l = s.split()
            # Read in the fixed columns
            for vcf_index, wt_index in fixed_columns:
                if l[vcf_index] != MISSING_VALUE:
                    row[wt_index] = l[vcf_index] 
                    #t.insert_encoded_elements(col.position, l[index])
                    #self._insert_elements(col, l[index])
            # Now process the info columns.
            for mapping in l[7].split(b";"):
                tokens = mapping.split(b"=")
                name = tokens[0]
                if name in info_columns:
                    col = info_columns[name]
                    if len(tokens) == 2:
                        row[col] = tokens[1]
                        #t.insert_encoded_elements(col.position, tokens[1])
                        #self._insert_elements(col, tokens[1])
                    else:
                        # This is a Flag column.
                        row[col] = b"1"
                        #t.insert_elements(col.position, [1])
            # Process the genotype columns. 
            j = 0
            fmt = l[8].split(b":")
            for genotype_values in l[9:]:
                tokens = genotype_values.split(b":")
                if len(tokens) == len(fmt):
                    for k in range(len(fmt)):
                        if fmt[k] in genotype_columns[j]:
                            col = genotype_columns[j][fmt[k]]
                            row[col] = tokens[k]
                            #t.insert_encoded_elements(col.position, tokens[k])
                            #self._insert_elements(col, tokens[k])
                elif len(tokens) > 1:
                    # We can treat a genotype value on its own as missing values.
                    # We can have skipped columns at the end though, which we 
                    # should deal with properly. So, put in a loud complaint 
                    # here and fix later.
                    print("PARSING CORNER CASE NOT HANDLED!!! FIXME!!!!")
                j += 1
            yield row
            # Finally, commit the record.
            #self._row_buffer.commit_row()
            #num_rows += 1
            #if num_rows % self._progress_update_rows == 0:
            #    self._update_progress()



def main():
    prog_description = "Convert VCF file to Wormtable format."
    parser = argparse.ArgumentParser(description=prog_description) 
    parser.add_argument("FILE", 
        help="VCF file to convert or - for stdin")   
    parser.add_argument("--progress", "-p", action="store_true", default=False,
        help="show progress monitor (not available for stdin)")   
    parser.add_argument("--force", "-f", action="store_true", default=False,
        help="force over-writing of existing wormtable")   
    parser.add_argument("--name", "-n", 
        help="name of the output wormtable.")   
    parser.add_argument("--cache-size", "-c", default="64M",
        help="cache size in bytes; suffixes K, M and G also supported.")   
    args = parser.parse_args()
    
    f = open(args.FILE, "rb")
    homedir = "tmp"
    table = wt.Table(homedir)

    vcf_parser = VCFParser(f)
    vcf_parser.generate_schema(table)
    table.open("w")
    table_columns = {}
    for c in table.columns():
        table_columns[c.get_name().encode()] = c.get_position()
    table.close()
    
    
    table.read_metadata(table.get_metadata_path())
    table.open("w")
    for r in vcf_parser.rows(table_columns):
        table.append_encoded(r)
    table.close()

if __name__ == "__main__":
    main()

