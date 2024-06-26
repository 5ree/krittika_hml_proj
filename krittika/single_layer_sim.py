import math
import os.path
import numpy
from scalesim.compute.operand_matrix import operand_matrix
from scalesim.memory.double_buffered_scratchpad_mem import double_buffered_scratchpad

from krittika.config.krittika_config import KrittikaConfig
from krittika.partition_manager import PartitionManager
from krittika.compute.compute_node import ComputeNode


class SingleLayerSim:
    '''
        The objective of this class is to:
        1. Read the operand matrices
        2. Get the schedule from the scheduler class object
        3. Partition the operand matrix
        4. Run the partitioned operand matrix for compute
        5. Run the generated demands from each compute element
    '''
    def __init__(self):

        # Member objects
        self.op_mat_obj = operand_matrix()
        self.partitioner_obj = PartitionManager()
        self.config_obj = KrittikaConfig()
        self.noc_obj    = None
        self.this_part_mem = None
        
        # Variables determining state
        self.layer_id = 0
        self.num_input_part = 0
        self.num_filter_part = 0
        self.compute_node_list = []
        self.all_node_mem_objects = []

        #
        self.log_top_path = './'

        # Reports: Per core
        self.total_cycles_list = []
        self.stall_cycles_list = []
        self.overall_util_list = []
        self.mapping_eff_list = []
        self.compute_util_list = []

        self.ifmap_sram_reads_list = []
        self.filter_sram_reads_list = []
        self.ofmap_sram_writes_list = []
        self.avg_ifmap_sram_bw_list = []
        self.avg_filter_sram_bw_list = []
        self.avg_ofmap_sram_bw_list = []

        self.ifmap_sram_start_cycle_list = []
        self.ifmap_sram_stop_cycle_list = []
        self.filter_sram_start_cycle_list = []
        self.filter_sram_stop_cycle_list = []
        self.ofmap_sram_start_cycle_list = []
        self.ofmap_sram_stop_cycle_list = []

        self.ifmap_dram_start_cycle_list = []
        self.ifmap_dram_stop_cycle_list = []
        self.filter_dram_start_cycle_list = []
        self.filter_dram_stop_cycle_list = []
        self.ofmap_dram_start_cycle_list = []
        self.ofmap_dram_stop_cycle_list = []

        self.ifmap_dram_reads_list = []
        self.filter_dram_reads_list = []
        self.ofmap_dram_writes_list = []

        self.avg_ifmap_dram_bw_list = []
        self.avg_filter_dram_bw_list = []
        self.avg_ofmap_dram_bw_list = []

        self.ifmap_demand_mat =[]
        self.filter_map_demand_mat = []
        self.ofmap_demand_mat = []

        # Flags
        self.verbose = True
        self.params_set = False
        self.compute_done = False
        self.mem_traces_done = False
        self.report_metrics_ready = False
        self.core_id=0
        self.skip_dram_reads=0
        self.skip_dram_writes=0
        self.num_cores = 0
        self.tile_number = -1

        self.tracking_id = {}
        self.pushed_in_time = {}

    #
    def set_params(self,
                   config_obj=KrittikaConfig(),
                   op_mat_obj=operand_matrix(),
                   partitioner_obj=PartitionManager(),
                   noc_obj = None,
                   layer_id=0,core_id=0,
                   verbosity=True,
                   log_top_path='./',skip_dram_reads=False,skip_dram_writes=False, num_cores= 1 , enable_lp_partition = 0 ):

        self.verbose = verbosity
        self.log_top_path = log_top_path

        self.config_obj = config_obj
        self.op_mat_obj = op_mat_obj
        self.partitioner_obj = partitioner_obj
        self.noc_obj    = noc_obj

        self.layer_id = layer_id
        self.core_id = core_id
        self.params_set = True
        self.skip_dram_reads = skip_dram_reads
        self.skip_dram_writes = skip_dram_writes
        self.num_cores = num_cores
        self.enable_lp_partition = enable_lp_partition
        self.per_tile_size = 0
        self.total_tiles_ifmap_layer =0 
        self.total_tiles_filter_map_layer=0
    #
    def run_single_layer_ls(self):
        self.num_input_part, self.num_filter_part = self.partitioner_obj.get_layer_partitions(layer_id=self.layer_id)

        self.compute_node_list = []

        self.run_compute_all_parts()
        self.run_mem_sim_all_parts()
    
    def run_single_layer_lp(self):

        self.num_input_part = 1
        self.num_filter_part = 1

        self.compute_node_list = []

        self.run_compute_all_parts()
   
    def run_single_layer_ls_tiled(self , noc_obj = None):

        self.num_input_part, self.num_filter_part = self.partitioner_obj.get_layer_partitions(layer_id=self.layer_id)
        
        self.compute_node_list = []

        self.run_compute_all_parts_tiled_noc()
        self.run_mem_sim_all_parts_tiled_noc(noc_obj)

    def run_compute_all_parts_tiled_noc(self):
        ifmap_matrix, filter_matrix, ofmap_matrix = self.op_mat_obj.get_all_operand_matrix()
        compute_unit, opt_dataflow = self.partitioner_obj.get_opt_compute_params(layer_id=self.layer_id)
        input_rows_per_part = math.ceil(ifmap_matrix.shape[0] / self.num_input_part)
        filter_cols_per_part = math.ceil(filter_matrix.shape[1] / self.num_filter_part)

        for inp_part in range(self.num_input_part):
            ifmap_row_start = inp_part * input_rows_per_part
            ifmap_row_end = min(ifmap_row_start + input_rows_per_part, ifmap_matrix.shape[0])
            ifmap_part = ifmap_matrix[ifmap_row_start:ifmap_row_end,:]
            for filt_part in range(self.num_filter_part):

                filt_col_start = filt_part * filter_cols_per_part
                filt_col_end = min(filt_col_start + filter_cols_per_part, filter_matrix.shape[1])

                filter_part = filter_matrix[:, filt_col_start: filt_col_end]
                ofmap_part = ofmap_matrix[ifmap_row_start: ifmap_row_end, filt_col_start:filt_col_end]

                this_part_compute_node = ComputeNode()
                this_part_compute_node.set_params(config=self.config_obj,
                                                  compute_unit=compute_unit,
                                                  dataflow=opt_dataflow)

                this_part_compute_node.set_operands(ifmap_opmat=ifmap_part,
                                                    filter_opmat=filter_part,
                                                    ofmap_opmat=ofmap_part)
                this_part_compute_node.calc_demand_matrices()
                
                this_part_compute_node.compute_node_total_tiles_ifmap_layer = this_part_compute_node.selected_compute_node.compute_unit.total_tiles_ifmap
                this_part_compute_node.compute_node_total_tiles_filter_map_layer  = this_part_compute_node.selected_compute_node.compute_unit.total_tiles_filter_map
                assert this_part_compute_node.compute_node_total_tiles_ifmap_layer == this_part_compute_node.compute_node_total_tiles_filter_map_layer
                this_part_compute_node.per_tile_size =  this_part_compute_node.selected_compute_node.compute_unit.ifmap_demand_matrix.shape[0]/ this_part_compute_node.compute_node_total_tiles_ifmap_layer
                self.compute_node_list += [this_part_compute_node]

        self.compute_done = True


    def run_compute_all_parts(self):
        ifmap_matrix, filter_matrix, ofmap_matrix = self.op_mat_obj.get_all_operand_matrix()
        compute_unit, opt_dataflow = self.partitioner_obj.get_opt_compute_params(layer_id=self.layer_id)
        input_rows_per_part = math.ceil(ifmap_matrix.shape[0] / self.num_input_part)
        filter_cols_per_part = math.ceil(filter_matrix.shape[1] / self.num_filter_part)

        for inp_part in range(self.num_input_part):
            ifmap_row_start = inp_part * input_rows_per_part
            ifmap_row_end = min(ifmap_row_start + input_rows_per_part, ifmap_matrix.shape[0])
            ifmap_part = ifmap_matrix[ifmap_row_start:ifmap_row_end,:]
            for filt_part in range(self.num_filter_part):

                filt_col_start = filt_part * filter_cols_per_part
                filt_col_end = min(filt_col_start + filter_cols_per_part, filter_matrix.shape[1])

                filter_part = filter_matrix[:, filt_col_start: filt_col_end]
                ofmap_part = ofmap_matrix[ifmap_row_start: ifmap_row_end, filt_col_start:filt_col_end]

                this_part_compute_node = ComputeNode()
                this_part_compute_node.set_params(config=self.config_obj,
                                                  compute_unit=compute_unit,
                                                  dataflow=opt_dataflow)

                this_part_compute_node.set_operands(ifmap_opmat=ifmap_part,
                                                    filter_opmat=filter_part,
                                                    ofmap_opmat=ofmap_part)
                this_part_compute_node.calc_demand_matrices()
                
                self.total_tiles_ifmap_layer = this_part_compute_node.selected_compute_node.compute_unit.total_tiles_ifmap
                self.total_tiles_filter_map_layer  = this_part_compute_node.selected_compute_node.compute_unit.total_tiles_filter_map
            
            
                assert self.total_tiles_ifmap_layer == self.total_tiles_filter_map_layer
                if(self.total_tiles_ifmap_layer):
                    self.per_tile_size =  this_part_compute_node.selected_compute_node.compute_unit.ifmap_demand_matrix.shape[0]/ self.total_tiles_ifmap_layer
                else:
                    self.per_tile_size = this_part_compute_node.selected_compute_node.compute_unit.ifmap_demand_matrix.shape[0]
                
                self.compute_node_list += [this_part_compute_node]

        self.compute_done = True
        
    #
    def run_simd_all_parts(self, operand_matrix, optype = 'relu'):
        
        self.num_input_part = 1
        self.num_filter_part = self.config_obj.get_num_cores()

        input_rows_per_part = math.ceil((operand_matrix.shape[0]) / (self.num_input_part*self.num_filter_part))

        for inp_part in range(self.num_input_part):
            for filt_part in range(self.num_filter_part):

                operand_row_start = (inp_part+filt_part) * input_rows_per_part
                operand_row_end = operand_row_start + input_rows_per_part
                if operand_row_end > operand_matrix.shape[0]:
                    operand_row_end = operand_matrix.shape[0]

                operand_part = operand_matrix[operand_row_start: operand_row_end, :]

                this_part_compute_node = ComputeNode()
                this_part_compute_node.set_params(config=self.config_obj,
                                                  compute_unit='simd', optype = optype)

                this_part_compute_node.set_operands(ifmap_opmat=operand_part)

                self.compute_node_list += [this_part_compute_node]

        self.compute_done = True


    #
    def run_mem_sim_all_parts(self):
        assert self.compute_done

        
        bandwidth_mode = True
        if (self.config_obj.get_bandwidth_use_mode()=="USER"):
            bandwidth_mode = False
        per_core_ifmap_buf_size, per_core_fitler_buf_size, per_core_ofmap_buf_size \
            = ([i * 1024 for i in self.config_obj.get_per_unit_sram_sizes_kb()])

        per_core_ifmap_bw, per_core_filter_bw, per_core_ofmap_bw\
            = self.config_obj.get_interface_bandwidths()

        for compute_node in self.compute_node_list:

            this_part_mem = double_buffered_scratchpad()
            this_part_mem.set_params(verbose=self.verbose,
                                    estimate_bandwidth_mode=bandwidth_mode,
                                    ifmap_buf_size_bytes=per_core_ifmap_buf_size,
                                    filter_buf_size_bytes=per_core_fitler_buf_size,
                                    ofmap_buf_size_bytes=per_core_ofmap_buf_size,
                                    ifmap_backing_buf_bw=per_core_ifmap_bw,
                                    filter_backing_buf_bw=per_core_filter_bw,
                                    ofmap_backing_buf_bw=per_core_ofmap_bw,
                                     )

            # Demand mat
            this_node_ifmap_demand_mat, this_node_filter_demand_mat, this_node_ofmap_demand_mat \
                = compute_node.get_demand_matrices()

            this_node_ifmap_fetch_mat, this_node_filter_fetch_mat = compute_node.get_prefetch_matrices()
            if (self.config_obj.get_bandwidth_use_mode()=="USER"):
                this_part_mem.set_read_buf_prefetch_matrices(ifmap_prefetch_mat=this_node_ifmap_fetch_mat,
                                                         filter_prefetch_mat=this_node_filter_fetch_mat
                                                         )
            this_part_mem.service_memory_requests(this_node_ifmap_demand_mat,
                                                  this_node_filter_demand_mat,
                                                  this_node_ofmap_demand_mat,self.layer_id)

            self.all_node_mem_objects += [this_part_mem]

        self.mem_traces_done = True
###########################################################
    def setup_again_parameter(self):
        assert self.compute_done

        bandwidth_mode = True
        if (self.config_obj.get_bandwidth_use_mode()=="USER"):
            bandwidth_mode = False
        per_core_ifmap_buf_size, per_core_fitler_buf_size, per_core_ofmap_buf_size \
            = ([i * 1024 for i in self.config_obj.get_per_unit_sram_sizes_kb()])

        per_core_ifmap_bw, per_core_filter_bw, per_core_ofmap_bw\
            = self.config_obj.get_interface_bandwidths()
        skip_dram_reads = self.skip_dram_reads
        skip_dram_writes = self.skip_dram_writes
        rd_buf_active_frac = 0.999
        wr_buf_active_frac = 0.999## Pass this as a knob TODO
        
        if(self.skip_dram_reads and self.layer_id == 0 ): ## In LP, the first core is needs to read from mem and last core neesd to write from mem
            skip_dram_reads = 0
            rd_frac = 0.999
        if(self.skip_dram_writes and self.layer_id == (self.num_cores - 1) ): ## In LP, the first core is needs to read from mem and last core neesd to write from mem
            skip_dram_writes = 0
            wr_frac = 0.999
        # TODO hard coded fix thr avoe
        for compute_node in self.compute_node_list:

            self.this_part_mem.set_params(verbose=self.verbose,
                                     estimate_bandwidth_mode=bandwidth_mode,
                                     ifmap_buf_size_bytes=per_core_ifmap_buf_size,
                                     filter_buf_size_bytes=per_core_fitler_buf_size,
                                     ofmap_buf_size_bytes=per_core_ofmap_buf_size,
                                     ifmap_backing_buf_bw=per_core_ifmap_bw,
                                     filter_backing_buf_bw=per_core_filter_bw,
                                     ofmap_backing_buf_bw=per_core_ofmap_bw,
                                     skip_dram_reads = skip_dram_reads,
                                     skip_dram_writes = skip_dram_writes,
                                     rd_buf_active_frac = rd_buf_active_frac ,
                                     wr_buf_active_frac = wr_buf_active_frac
                                     )

            # Demand mat
            self.ifmap_demand_mat, self.filter_demand_mat, self.ofmap_demand_mat \
                = compute_node.get_demand_matrices()   
            this_node_ifmap_fetch_mat, this_node_filter_fetch_mat = compute_node.get_prefetch_matrices()
            if (self.config_obj.get_bandwidth_use_mode()=="USER"):
                self.this_part_mem.set_read_buf_prefetch_matrices(ifmap_prefetch_mat=this_node_ifmap_fetch_mat,
                                                         filter_prefetch_mat=this_node_filter_fetch_mat
                                                         )  
            

    def setup_memory(self, skip_adding_mem_objects = 0):  ## TODO can be moved to setup memory itself.
        assert self.compute_done

        bandwidth_mode = True
        if (self.config_obj.get_bandwidth_use_mode()=="USER"):
            bandwidth_mode = False
        per_core_ifmap_buf_size, per_core_fitler_buf_size, per_core_ofmap_buf_size \
            = ([i * 1024 for i in self.config_obj.get_per_unit_sram_sizes_kb()])

        per_core_ifmap_bw, per_core_filter_bw, per_core_ofmap_bw\
            = self.config_obj.get_interface_bandwidths()
        skip_dram_reads = self.skip_dram_reads
        skip_dram_writes = self.skip_dram_writes
        rd_buf_active_frac = 0.99
        wr_buf_active_frac = 0.99 ## Pass this as a knob TODO
        
        if(self.skip_dram_reads and self.layer_id == 0 ): ## In LP, the first core is needs to read from mem and last core neesd to write from mem
            skip_dram_reads = 0
            rd_frac = 0.999
        if(self.skip_dram_writes and self.layer_id == (self.num_cores - 1) ): ## In LP, the first core is needs to read from mem and last core neesd to write from mem
            skip_dram_writes = 0
            wr_frac = 0.999
        # TODO hard coded fix thr avoe
        
        for compute_node in self.compute_node_list:

            self.this_part_mem = double_buffered_scratchpad()
            self.this_part_mem.set_params(verbose=self.verbose,
                                     estimate_bandwidth_mode=bandwidth_mode,
                                     ifmap_buf_size_bytes=per_core_ifmap_buf_size,
                                     filter_buf_size_bytes=per_core_fitler_buf_size,
                                     ofmap_buf_size_bytes=per_core_ofmap_buf_size,
                                     ifmap_backing_buf_bw=per_core_ifmap_bw,
                                     filter_backing_buf_bw=per_core_filter_bw,
                                     ofmap_backing_buf_bw=per_core_ofmap_bw,
                                     skip_dram_reads = skip_dram_reads,
                                     skip_dram_writes = skip_dram_writes,
                                     rd_buf_active_frac = rd_buf_active_frac ,
                                     wr_buf_active_frac = wr_buf_active_frac
                                     )

            # Demand mat
            self.ifmap_demand_mat, self.filter_demand_mat, self.ofmap_demand_mat \
                = compute_node.get_demand_matrices()   
            this_node_ifmap_fetch_mat, this_node_filter_fetch_mat = compute_node.get_prefetch_matrices()
            if (self.config_obj.get_bandwidth_use_mode()=="USER"):
                self.this_part_mem.set_read_buf_prefetch_matrices(ifmap_prefetch_mat=this_node_ifmap_fetch_mat,
                                                         filter_prefetch_mat=this_node_filter_fetch_mat
                                                         )  
            
                
            self.all_node_mem_objects += [self.this_part_mem] ## This is usualyl done for mem requests.
            
    


    def run_mem_sim_all_parts_lp(self, core_id, init_time): ## Why does this need time again?
        assert self.compute_done
       
        completed = 0
        if(self.tile_number + 1 <= 0):
            return 0 
        
        if(self.tile_number >= (self.total_tiles_ifmap_layer)): # / 3 + self.total_tiles_ifmap_layer % 3 )): ## asset checks if they iofmap and filter tiles are same always
            return  1 ## This should say you are done for this core id.
        #print("Inside mem sim all parts lp for core id",core_id,",  total tiles",self.total_tiles_ifmap_layer,"Init time",init_time)
        for compute_node in self.compute_node_list: ## Can remove this. TODO DO we need it tto loop 
            # Demand mat
            
            row_start = int(self.tile_number * 1* self.per_tile_size)
            row_end = row_start + 1*int(self.per_tile_size)
            row_end = min(row_end,self.ofmap_demand_mat.shape[0])
            

            
            this_tile_ifmap_demand_mat = self.ifmap_demand_mat[ row_start : row_end ]
            this_tile_filter_demand_mat =  self.filter_demand_mat[ row_start : row_end ]
            this_tile_ofmap_demand_mat = self.ofmap_demand_mat[ row_start : row_end ]         

            
            self.this_part_mem.service_memory_requests_multiple_times( this_tile_ifmap_demand_mat,
            this_tile_filter_demand_mat,this_tile_ofmap_demand_mat,core_id, self.tile_number,init_time, 
            (self.tile_number == self.total_tiles_ifmap_layer - 1)) ## hopefullt this object wont be destroye when gone out of scope.

        self.mem_traces_done = True ## Wll this be valid? as we need each layer to be done to set this TODO

        return completed



    def run_mem_sim_all_parts_tiled_noc(self, noc_obj = None): ## Why does this need time again?
        assert self.compute_done
        assert noc_obj
        
        bandwidth_mode = True
        if (self.config_obj.get_bandwidth_use_mode()=="USER"):
            bandwidth_mode = False
        per_core_ifmap_buf_size, per_core_fitler_buf_size, per_core_ofmap_buf_size \
            = ([i * 1024 for i in self.config_obj.get_per_unit_sram_sizes_kb()])

        per_core_ifmap_bw, per_core_filter_bw, per_core_ofmap_bw\
            = self.config_obj.get_interface_bandwidths()
        iterator = 0
        this_part_mem ={}
        this_node_ifmap_demand_mat ={}#[i for i in range(len(self.compute_node_list))]
        this_node_filter_demand_mat ={} #[i for i in range(len(self.compute_node_list))]
        this_node_ofmap_demand_mat ={} #[i for i in range(len(self.compute_node_list))]

        for compute_node in self.compute_node_list:

            this_part_mem[iterator] = double_buffered_scratchpad()
            this_part_mem[iterator].set_params(verbose=self.verbose,
                                    estimate_bandwidth_mode=bandwidth_mode,
                                    ifmap_buf_size_bytes=per_core_ifmap_buf_size,
                                    filter_buf_size_bytes=per_core_fitler_buf_size,
                                    ofmap_buf_size_bytes=per_core_ofmap_buf_size,
                                    ifmap_backing_buf_bw=per_core_ifmap_bw,
                                    filter_backing_buf_bw=per_core_filter_bw,
                                    ofmap_backing_buf_bw=per_core_ofmap_bw,
                                     )

            # Demand mat
            this_node_ifmap_demand_mat[iterator], this_node_filter_demand_mat[iterator], this_node_ofmap_demand_mat[iterator] \
                = compute_node.get_demand_matrices()
            
            
            this_node_ifmap_fetch_mat, this_node_filter_fetch_mat = compute_node.get_prefetch_matrices()
            
            
            if (self.config_obj.get_bandwidth_use_mode()=="USER"):
                this_part_mem[iterator].set_read_buf_prefetch_matrices(ifmap_prefetch_mat=this_node_ifmap_fetch_mat,
                                                         filter_prefetch_mat=this_node_filter_fetch_mat
                                                         )
            self.all_node_mem_objects += [this_part_mem[iterator]]
            iterator+=1
        completed = 0
        time_current = {} # should be moved later
        for core_id in range(len(self.compute_node_list)):
            self.compute_node_list[core_id].tile_number = 0
            time_current[core_id] = 0
        noc_total_time = 0

        while(completed != len(self.compute_node_list)):
            
            completed = 0
            for core_id in range(len(self.compute_node_list)):
                
                
                completed_per_core = 0
                if(self.compute_node_list[core_id].tile_number >= (self.compute_node_list[core_id].compute_node_total_tiles_ifmap_layer)): # / 3 + self.total_tiles_ifmap_layer % 3 )): ## asset checks if they iofmap and filter tiles are same always
                    completed_per_core =  1 ## This should say you are done for this core id.
                completed += completed_per_core
                if(completed_per_core == 1):
                    continue
                # Demand mat
                
                row_start = int(self.compute_node_list[core_id].tile_number * 1* self.compute_node_list[core_id].per_tile_size)
                row_end = row_start + 1*int(self.compute_node_list[core_id].per_tile_size)
                
                this_tile_ifmap_demand_mat = this_node_ifmap_demand_mat[core_id][ row_start : row_end ]
                this_tile_filter_demand_mat =  this_node_filter_demand_mat[core_id][ row_start : row_end ]
                this_tile_ofmap_demand_mat = this_node_ofmap_demand_mat[core_id][ row_start : row_end ]        
                
                
                this_part_mem[core_id].service_memory_requests_multiple_times_ls_tiled( this_tile_ifmap_demand_mat,
                this_tile_filter_demand_mat,this_tile_ofmap_demand_mat,core_id, self.compute_node_list[core_id].tile_number,time_current[core_id], 
                (self.compute_node_list[core_id].tile_number == self.compute_node_list[core_id].compute_node_total_tiles_ifmap_layer - 1),noc_obj , 1, self.tracking_id, self.pushed_in_time ) ## hopefullt this object wont be destroye when gone out of scope.
                self.mem_traces_done = True ## IDK if this should be here. IN LP code it was here so/
                
                time_current[core_id] = time_current[core_id] + this_part_mem[core_id].cycles_per_tile
                self.compute_node_list[core_id].tile_number+=1
        completed = 0
        noc_total_time = 0
        
        for core_id in range(len(self.compute_node_list)):
            self.compute_node_list[core_id].tile_number = 0
            time_current[core_id] = 0
            self.all_node_mem_objects[core_id].reset_buffer_states()
            
            self.all_node_mem_objects[core_id].set_params(verbose=self.verbose,
                                    estimate_bandwidth_mode=bandwidth_mode,
                                    ifmap_buf_size_bytes=per_core_ifmap_buf_size,
                                    filter_buf_size_bytes=per_core_fitler_buf_size,
                                    ofmap_buf_size_bytes=per_core_ofmap_buf_size,
                                    ifmap_backing_buf_bw=per_core_ifmap_bw,
                                    filter_backing_buf_bw=per_core_filter_bw,
                                    ofmap_backing_buf_bw=per_core_ofmap_bw,
                                     )
            this_node_ifmap_fetch_mat, this_node_filter_fetch_mat = self.compute_node_list[core_id].get_prefetch_matrices()
            if (self.config_obj.get_bandwidth_use_mode()=="USER"):
                self.all_node_mem_objects[core_id].set_read_buf_prefetch_matrices(ifmap_prefetch_mat=this_node_ifmap_fetch_mat,
                                                         filter_prefetch_mat=this_node_filter_fetch_mat
                                                         )
        
        noc_obj.deliver_all_txns()

        while(completed != len(self.compute_node_list)):
            
            completed = 0
            for core_id in range(len(self.compute_node_list)):
                
                completed_per_core = 0
                if(self.compute_node_list[core_id].tile_number >= (self.compute_node_list[core_id].compute_node_total_tiles_ifmap_layer)): # / 3 + self.total_tiles_ifmap_layer % 3 )): ## asset checks if they iofmap and filter tiles are same always
                    completed_per_core =  1 ## This should say you are done for this core id.
                completed += completed_per_core
                if(completed_per_core == 1):
                    continue
                # Demand mat
                
                row_start = int(self.compute_node_list[core_id].tile_number * 1* self.compute_node_list[core_id].per_tile_size)
                row_end = row_start + 1*int(self.compute_node_list[core_id].per_tile_size)
                this_tile_ifmap_demand_mat = this_node_ifmap_demand_mat[core_id][ row_start : row_end ]
                this_tile_filter_demand_mat =  this_node_filter_demand_mat[core_id][ row_start : row_end ]
                this_tile_ofmap_demand_mat = this_node_ofmap_demand_mat[core_id][ row_start : row_end ]        
               
                
                self.all_node_mem_objects[core_id].service_memory_requests_multiple_times_ls_tiled( this_tile_ifmap_demand_mat,
                this_tile_filter_demand_mat,this_tile_ofmap_demand_mat,core_id, self.compute_node_list[core_id].tile_number,time_current[core_id], 
                (self.compute_node_list[core_id].tile_number == self.compute_node_list[core_id].compute_node_total_tiles_ifmap_layer - 1),noc_obj , 0, self.tracking_id, self.pushed_in_time ) ## hopefullt this object wont be destroye when gone out of scope.
                self.mem_traces_done = True ## IDK if this should be here. IN LP code it was here so/
                

                time_current[core_id] = time_current[core_id] + self.all_node_mem_objects[core_id].cycles_per_tile
                self.compute_node_list[core_id].tile_number+=1
        
   
        max_time = time_current[0]
        for core_id in range(len(self.compute_node_list)):
            if(max_time < time_current[core_id] ):
                max_time = time_current[core_id]
        print("Run time",max_time)
###################################################################################################
    # 
    def gather_simd_report_items_across_cores(self):
        assert self.compute_done
        for core_id in range(len(self.compute_node_list)):
            compute_system = self.compute_node_list[core_id]

            # Compute report
            num_compute = compute_system.get_num_compute()
            num_unit = compute_system.get_num_units()
            total_cycles = compute_system.get_total_cycles()
            
            stall_cycles = 0
            if(total_cycles):
                overall_util = (num_compute * 100) / (total_cycles * num_unit)
            else:
                overall_util = 0
            mapping_eff = compute_system.get_avg_mapping_efficiency() * 100
            compute_util = compute_system.get_avg_compute_utilization() * 100

            self.total_cycles_list += [total_cycles]
            self.stall_cycles_list += [stall_cycles]
            self.overall_util_list += [overall_util]
            self.mapping_eff_list += [mapping_eff]
            self.compute_util_list += [compute_util]

    #
    def gather_report_items_across_cores(self):
        assert self.compute_done and self.mem_traces_done
        for core_id in range(len(self.compute_node_list)):
            compute_system = self.compute_node_list[core_id]
            memory_system = self.all_node_mem_objects[core_id]
            
            # Compute report
            num_compute = compute_system.get_num_compute()
            print(num_compute)
            num_unit = compute_system.get_num_units()
            if(self.enable_lp_partition == 1):
                
                total_cycles = memory_system.get_total_compute_cycles() ##+ self.noc_obj.get_latency(compute_system.tracking_id) # + DEPENDENCY BUBBLES LOLDBG
            else:
                total_cycles = memory_system.get_total_compute_cycles() 
            # Manish SRAM to SRAM may help with adding the dependency cycles
            stall_cycles = memory_system.get_stall_cycles()
            if(total_cycles):
                overall_util = (num_compute * 100) / (total_cycles * num_unit)
            else:
                overall_util = 0
            mapping_eff = compute_system.get_avg_mapping_efficiency() * 100
            compute_util = compute_system.get_avg_compute_utilization() * 100

            self.total_cycles_list += [total_cycles]
            self.stall_cycles_list += [stall_cycles]
            self.overall_util_list += [overall_util]
            self.mapping_eff_list += [mapping_eff]
            self.compute_util_list += [compute_util]

            # BW report
            ifmap_sram_reads = compute_system.get_ifmap_requests()
            filter_sram_reads = compute_system.get_filter_requests()
            ofmap_sram_writes = compute_system.get_ofmap_requests()
            if(total_cycles):
                avg_ifmap_sram_bw = ifmap_sram_reads / total_cycles
                avg_filter_sram_bw = filter_sram_reads / total_cycles
                avg_ofmap_sram_bw = ofmap_sram_writes / total_cycles
            else:
                avg_ifmap_sram_bw = 0 
                avg_filter_sram_bw = 0
                avg_ofmap_sram_bw = 0
            self.ifmap_sram_reads_list += [ifmap_sram_reads]
            self.filter_sram_reads_list += [filter_sram_reads]
            self.ofmap_sram_writes_list += [ofmap_sram_writes]
            self.avg_ifmap_sram_bw_list += [avg_ifmap_sram_bw]
            self.avg_filter_sram_bw_list += [avg_filter_sram_bw]
            self.avg_ofmap_sram_bw_list += [avg_ofmap_sram_bw]

            # Detail report
            ifmap_sram_start_cycle, ifmap_sram_stop_cycle = memory_system.get_ifmap_sram_start_stop_cycles()
            filter_sram_start_cycle, filter_sram_stop_cycle = memory_system.get_filter_sram_start_stop_cycles()
            ofmap_sram_start_cycle, ofmap_sram_stop_cycle = memory_system.get_ofmap_sram_start_stop_cycles()

            ifmap_dram_start_cycle, ifmap_dram_stop_cycle, ifmap_dram_reads = memory_system.get_ifmap_dram_details()
            filter_dram_start_cycle, filter_dram_stop_cycle, filter_dram_reads = memory_system.get_filter_dram_details()
            ofmap_dram_start_cycle, ofmap_dram_stop_cycle, ofmap_dram_writes = memory_system.get_ofmap_dram_details()

            self.ifmap_sram_start_cycle_list += [ifmap_sram_start_cycle]
            self.ifmap_sram_stop_cycle_list += [ifmap_sram_stop_cycle]
            self.filter_sram_start_cycle_list += [filter_sram_start_cycle]
            self.filter_sram_stop_cycle_list += [filter_sram_stop_cycle]
            self.ofmap_sram_start_cycle_list += [ofmap_sram_start_cycle]
            self.ofmap_sram_stop_cycle_list += [ofmap_sram_stop_cycle]

            self.ifmap_dram_start_cycle_list += [ifmap_dram_start_cycle]
            self.ifmap_dram_stop_cycle_list += [ifmap_dram_stop_cycle]
            self.filter_dram_start_cycle_list += [filter_dram_start_cycle]
            self.filter_dram_stop_cycle_list += [filter_dram_stop_cycle]
            self.ofmap_dram_start_cycle_list += [ofmap_dram_start_cycle]
            self.ofmap_dram_stop_cycle_list += [ofmap_dram_stop_cycle]

            self.ifmap_dram_reads_list += [ifmap_dram_reads]
            self.filter_dram_reads_list += [filter_dram_reads]
            self.ofmap_dram_writes_list += [ofmap_dram_writes]

            # BW calc for DRAM access
            avg_ifmap_dram_bw = ifmap_dram_reads / (ifmap_dram_stop_cycle - ifmap_dram_start_cycle + 1)
            avg_filter_dram_bw = filter_dram_reads / (filter_dram_stop_cycle - filter_dram_start_cycle + 1)
            avg_ofmap_dram_bw = ofmap_dram_writes / (ofmap_dram_stop_cycle - ofmap_dram_start_cycle + 1)

            self.avg_ifmap_dram_bw_list += [avg_ifmap_dram_bw]
            self.avg_filter_dram_bw_list += [avg_filter_dram_bw]
            self.avg_ofmap_dram_bw_list += [avg_ofmap_dram_bw]

        self.report_metrics_ready = True

    #
    def save_traces(self,enable_ls_file_saving = 0):
        assert self.mem_traces_done
        self.build_trace_log_dirs(enable_ls_file_saving)
        #len(self.all_node_mem_objects))
        for part_idx in range(len(self.all_node_mem_objects)):
            #print("Which core id bro",part_idx)
            if(enable_ls_file_saving == 1):
                trace_dir_name = self.log_top_path + \
                             '/traces/layer' + str(self.layer_id) + \
                             '/core' + str(part_idx)
            else:
                trace_dir_name = self.log_top_path + \
                             '/traces/layer' + str(self.layer_id) + \
                             '/core' + str(self.layer_id)  # str(part_idx) ## TODO Mmanchali fix it have core id.
                             # currently this is run for each layer and since only 1 layer has 1 core executing it assumes it to be core 0, Need to fix this
            
            ifmap_sram_filename = trace_dir_name + '/IFMAP_SRAM_TRACE.csv'
            filter_sram_filename = trace_dir_name + '/FILTER_SRAM_TRACE.csv'
            ofmap_sram_filename = trace_dir_name + '/OFMAP_SRAM_TRACE.csv'

            ifmap_dram_filename = trace_dir_name + '/IFMAP_DRAM_TRACE.csv'
            filter_dram_filename = trace_dir_name + '/FILTER_DRAM_TRACE.csv'
            ofmap_dram_filename = trace_dir_name + '/OFMAP_DRAM_TRACE.csv'
    
            memory_system = self.all_node_mem_objects[part_idx]
            memory_system.print_ifmap_sram_trace(ifmap_sram_filename)
            memory_system.print_ifmap_dram_trace(ifmap_dram_filename)
            memory_system.print_filter_sram_trace(filter_sram_filename)
            memory_system.print_filter_dram_trace(filter_dram_filename)
            memory_system.print_ofmap_sram_trace(ofmap_sram_filename)
            memory_system.print_ofmap_dram_trace(ofmap_dram_filename)

#
    def build_trace_log_dirs(self,enable_ls_file_saving = 0):
        self.check_and_build(self.log_top_path)
        
        l1_dir = self.log_top_path + '/traces'
        self.check_and_build(l1_dir)

        l2_dir = l1_dir + '/layer' + str(self.layer_id)
        self.check_and_build(l2_dir)

        for core_id in range(len(self.compute_node_list)):
            if(enable_ls_file_saving):
                this_core_dir = l2_dir + '/core' + str(core_id) ## Change this back to core_id
            else:    
                this_core_dir = l2_dir + '/core' + str(self.layer_id) ## Change this back to core_id
            self.check_and_build(this_core_dir)

    def get_ofmap_operand_matrix(self):
        
        if not self.compute_done:
            self.run_compute_all_parts()

        _, _, ofmap_matrix = self.op_mat_obj.get_all_operand_matrix()
        return ofmap_matrix



    @staticmethod
    def check_and_build(dirname):
        if not os.path.isdir(dirname):
            cmd = 'mkdir ' + dirname
            os.system(cmd)






