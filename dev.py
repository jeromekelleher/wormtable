from __future__ import print_function

"""
Development code.
"""
import os
import sys

import vcfdb

def create_index(homedir, column_names):
    print("creating index", homedir, column_names)
    table = vcfdb.Table(homedir)
    schema = table.get_schema()
    columns = [schema.get_column(name) for name in column_names] 
    index = vcfdb.Index(table, columns)

def main():

    if len(sys.argv) == 3: 
        homedir = sys.argv[1] 
        vcf_file = sys.argv[2]
        input_schema = os.path.join(homedir, "input_schema.xml")
        schema = vcfdb.vcf_schema_factory(vcf_file)
        schema.write_xml(input_schema)
        # In the command line tool we'll optionally stop here 
        # and allow the user to edit the schema. This means 
        # we don't have to generate the 'perfect' vcf schema.
        dbb = vcfdb.VCFTableBuilder(homedir, input_schema)
        dbb.set_cache_size(8 * 2**30) # 8 gigs - bigger is better
        dbb.set_buffer_size(64 * 2**20) # 64 megs
        dbb.build(vcf_file)
        
    elif len(sys.argv) == 2:
        table = vcfdb.Table(sys.argv[1])
        print("num rows = ", table.get_num_rows())
        v = 0
        for j in range(table.get_num_rows()):
            row = table.get_row(j)
            print("row", j)
            for k, v in row.items():
                print("\t", k, "->", v)
        table.close()
    else:
        create_index("db_NOBACKUP_/", [b"H27_DP"])
        
       
if __name__ == "__main__":
    main()
