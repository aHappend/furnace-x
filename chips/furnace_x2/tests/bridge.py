"""Generated public-port-only simulation bridges (written only into retained runs)."""


def top_bench(width):
    return r"""
`timescale 1ns/1ps
module tb;
localparam W=@WIDTH@, L=W/8;
reg clk=0, rst_n;
reg [W-1:0] s_axis_tdata=0;
reg [L-1:0] s_axis_tkeep=0;
reg s_axis_tvalid=0,s_axis_tlast=0;
wire s_axis_tready;
reg [1:0] s_check_enable=0;
reg [31:0] s_expected_crc32c=0;
reg [63:0] s_expected_crc64_nvme=0;
wire [W-1:0] m_axis_tdata;
wire [L-1:0] m_axis_tkeep;
wire m_axis_tvalid,m_axis_tlast,m_crc_valid,m_crc_protocol_error;
reg m_axis_tready=0,m_crc_ready=0,m_meta_ready=0;
wire [31:0] m_crc32c;
wire [63:0] m_crc64_nvme;
wire [1:0] m_crc_mismatch;
reg cfg_valid=0;
reg [1:0] cfg_op=0;
reg [5:0] cfg_index=0;
reg [511:0] cfg_value=0,cfg_mask=0;
reg [31:0] cfg_action=0;
reg cfg_enable=0;
reg [327:0] cfg_rss_key=0;
wire cfg_ready,m_meta_valid,m_rss_valid,m_rule_hit;
wire [511:0] m_header;
wire [31:0] m_packet_bytes,m_rss_hash,m_action;
wire [5:0] m_rule_index;
furnace_x2_top #(.DATA_WIDTH(W)) dut(.*);
wire [W-1:0] p_data;
wire [L-1:0] p_keep;
wire p_valid,p_last,p_cv,p_pe,p_ready;
wire [31:0] p_c32;
wire [63:0] p_c64;
wire [1:0] p_mm;
parent_x1_top #(.DATA_WIDTH(W)) parent (
 .clk(clk),.rst_n(rst_n),.s_axis_tdata(s_axis_tdata),.s_axis_tkeep(s_axis_tkeep),
 .s_axis_tvalid(s_axis_tvalid && s_axis_tready),.s_axis_tlast(s_axis_tlast),
 .s_axis_tready(p_ready),.s_check_enable(s_check_enable),
 .s_expected_crc32c(s_expected_crc32c),.s_expected_crc64_nvme(s_expected_crc64_nvme),
 .m_axis_tdata(p_data),.m_axis_tkeep(p_keep),.m_axis_tvalid(p_valid),
 .m_axis_tlast(p_last),.m_axis_tready(m_axis_tready),
 .m_crc_valid(p_cv),.m_crc_ready(m_crc_ready),.m_crc32c(p_c32),
 .m_crc64_nvme(p_c64),.m_crc_mismatch(p_mm),.m_crc_protocol_error(p_pe));
integer fd,transcript,rc,cmd,id=0,n=0,i,j,cycle=0,deadline=0,final_edge=-1;
integer sent=0,received=0,crc_received=0,meta_received=0,first_meta=0;
integer active=0,mode=0,abort_kind=0,bubble=0,packet_count=0,beat_count=0;
integer stalls_b=0,stalls_c=0,stalls_m=0,simultaneous=0,resets=0,configs=0;
integer ingress_bubbles=0;
integer deferred_cfg=0,deferred_count=0,priority_count=0;
reg [1:0] pending_op;
reg [5:0] pending_index;
reg [511:0] pending_value,pending_mask;
reg [31:0] pending_action,default_shadow=0;
reg pending_enable;
reg [327:0] pending_key;
integer ecerr,emm,erv,ehit,eidx,elen;
reg [W-1:0] bd[0:2047];
reg [L-1:0] bk[0:2047];
reg [1:0] bc[0:2047];
reg [31:0] b32[0:2047];
reg [63:0] b64[0:2047];
integer accepted_at[0:2047];
reg [31:0] ec32,ehash,eaction;
reg [63:0] ec64;
reg [511:0] eheader;
reg [31:0] observed_c32,observed_hash,observed_action;
reg [63:0] observed_c64;
reg [511:0] observed_header;
integer observed_length,observed_rss,observed_hit,observed_index;
reg held_b=0,held_c=0,held_m=0;
reg [W+L:0] hold_b;
reg [98:0] hold_c;
reg [615:0] hold_m;
wire [W+L:0] now_b={m_axis_tdata,m_axis_tkeep,m_axis_tlast};
wire [98:0] now_c={m_crc32c,m_crc64_nvme,m_crc_mismatch,m_crc_protocol_error};
wire [615:0] now_m={m_header,m_packet_bytes,m_rss_hash,m_rss_valid,m_rule_hit,m_rule_index,m_action};
task automatic report(input string record);
begin
 $display("%s",record);
 $fdisplay(transcript,"%s",record);
end endtask
task automatic reset_check;
begin
 if ({s_axis_tready,cfg_ready,m_axis_tdata,m_axis_tkeep,m_axis_tvalid,m_axis_tlast,
 m_crc_valid,m_crc32c,m_crc64_nvme,m_crc_mismatch,m_crc_protocol_error,
 m_meta_valid,m_header,m_packet_bytes,m_rss_hash,m_rss_valid,m_rule_hit,
 m_rule_index,m_action} !== 0) $fatal(1,"RESET_NONZERO cycle=%0d",cycle);
end endtask
always @(posedge clk or negedge clk) if (!rst_n && $time>0) reset_check();
task automatic observe;
begin
 if (rst_n) begin
  if ((^{s_axis_tready,cfg_ready,m_axis_tvalid,m_crc_valid,m_meta_valid})===1'bx)
   $fatal(1,"ACTIVE_XZ control cycle=%0d",cycle);
  if (held_b && (!m_axis_tvalid || now_b !== hold_b)) $fatal(1,"UNSTABLE_PAYLOAD");
  if (held_c && (!m_crc_valid || now_c !== hold_c)) $fatal(1,"UNSTABLE_CRC");
  if (held_m && (!m_meta_valid || now_m !== hold_m)) $fatal(1,"UNSTABLE_META");
  held_b=m_axis_tvalid && !m_axis_tready; hold_b=now_b;
  held_c=m_crc_valid && !m_crc_ready; hold_c=now_c;
  held_m=m_meta_valid && !m_meta_ready; hold_m=now_m;
  if (held_b) stalls_b=stalls_b+1;
  if (held_c) stalls_c=stalls_c+1;
  if (held_m) stalls_m=stalls_m+1;
  if (active && sent>0 && cfg_ready) $fatal(1,"CONFIG_ACCEPT_DURING_PACKET");
  if (active && sent>0 && final_edge<0 && !s_axis_tvalid) ingress_bubbles=ingress_bubbles+1;
  if (active && final_edge>=0 && s_axis_tready) $fatal(1,"NEXT_PACKET_TOO_EARLY");
  if (m_axis_tvalid) begin
   if (!active || received>=sent) $fatal(1,"DUPLICATE_PAYLOAD id=%0d",id);
   if (now_b !== {bd[received],bk[received],(received==n-1)})
    $fatal(1,"PAYLOAD_MISMATCH id=%0d beat=%0d",id,received);
   if (mode==0 && cycle-accepted_at[received]!=16)
    $fatal(1,"PAYLOAD_LATENCY id=%0d observed=%0d",id,cycle-accepted_at[received]-1);
   if (m_axis_tready) begin received=received+1; beat_count=beat_count+1; end
  end
  if (m_crc_valid) begin
   if (!active || crc_received || final_edge<0) $fatal(1,"DUPLICATE_CRC id=%0d",id);
   if (now_c !== {ec32,ec64,2'(emm),1'(ecerr)})
    $fatal(1,"CRC_MISMATCH id=%0d actual=%h expected=%h",id,now_c,{ec32,ec64,2'(emm),1'(ecerr)});
   if (mode==0 && cycle-final_edge!=16) $fatal(1,"CRC_LATENCY id=%0d",id);
   if (m_crc_ready) begin
    crc_received=1;observed_c32=m_crc32c;observed_c64=m_crc64_nvme;
   end
  end
  if (m_meta_valid) begin
   if (!active || meta_received || final_edge<0) $fatal(1,"DUPLICATE_META id=%0d",id);
   if (now_m !== {eheader,32'(elen),ehash,1'(erv),1'(ehit),6'(eidx),eaction})
    $fatal(1,"META_MISMATCH id=%0d actual=%h expected=%h",id,now_m,
        {eheader,32'(elen),ehash,1'(erv),1'(ehit),6'(eidx),eaction});
   if (m_meta_ready) begin
    meta_received=1;observed_header=m_header;observed_length=m_packet_bytes;
    observed_hash=m_rss_hash;observed_rss=m_rss_valid;
    observed_hit=m_rule_hit;observed_index=m_rule_index;observed_action=m_action;
   end
  end
  if (m_meta_valid && m_meta_ready && m_crc_valid && m_crc_ready &&
      m_axis_tvalid && m_axis_tready && m_axis_tlast) simultaneous=simultaneous+1;
  if ({m_axis_tdata,m_axis_tkeep,m_axis_tvalid,m_axis_tlast,m_crc_valid,
       m_crc32c,m_crc64_nvme,m_crc_mismatch,m_crc_protocol_error} !==
      {p_data,p_keep,p_valid,p_last,p_cv,p_c32,p_c64,p_mm,p_pe})
    $fatal(1,"PARENT_COMPATIBILITY cycle=%0d",cycle);
 end
end endtask
task automatic tick;
begin
 #5;
 observe();
 if (rst_n && s_axis_tvalid && s_axis_tready) begin
  accepted_at[sent]=cycle; sent=sent+1;
  if (s_axis_tlast) final_edge=cycle;
  else if(mode!=0 && sent%3==0) bubble=2;
 end
 clk=1;
 #1;
 if (!rst_n) reset_check();
 if (rst_n && active && m_meta_valid && !first_meta) begin
  first_meta=1;
  if (cycle-final_edge!=1196)
   $fatal(1,"META_LATENCY id=%0d observed=%0d expected=1196",id,cycle-final_edge);
  if (now_m !== {eheader,32'(elen),ehash,1'(erv),1'(ehit),6'(eidx),eaction})
   $fatal(1,"META_MISMATCH id=%0d at publication actual=%h expected=%h",id,now_m,
       {eheader,32'(elen),ehash,1'(erv),1'(ehit),6'(eidx),eaction});
 end
 #4; clk=0;
 cycle=cycle+1;
end endtask
task automatic reset_dut;
begin
 rst_n=0; s_axis_tvalid=0; cfg_valid=0;
 #1; reset_check(); tick(); tick();
 active=0; held_b=0; held_c=0; held_m=0;
 default_shadow=0;rst_n=1; resets=resets+1;
end endtask
task automatic set_ready;
begin
 if (mode==0) begin m_axis_tready=1;m_crc_ready=1;m_meta_ready=1; end
 else if (mode==2) begin
  m_crc_ready=(final_edge>=0 && cycle-final_edge>=1220);
  m_axis_tready=(m_axis_tvalid && !m_axis_tlast) || m_crc_ready;
  m_meta_ready=m_crc_ready;
 end else begin
  m_axis_tready=(cycle%11>=4);
  m_crc_ready=(cycle%17>=8);
  m_meta_ready=(final_edge>=0 && cycle-final_edge>=1210 && cycle%7>=3);
 end
end endtask
initial begin
 rst_n=0;
`ifndef VERILATOR
 #0; reset_check();
`else
 #1; reset_check();
`endif
 tick(); tick(); rst_n=1;
 transcript=$fopen("transcript.txt","w");
 if (!transcript) $fatal(1,"NO_TRANSCRIPT");
 fd=$fopen("stimulus.txt","r");
 if (!fd) $fatal(1,"NO_STIMULUS");
 while (!$feof(fd)) begin
  rc=$fscanf(fd,"%d",cmd);
  if (rc==1) begin
   if (cmd==0) begin
    rc=$fscanf(fd,"%d %d %h %h %h %d %h",j,i,cfg_value,cfg_mask,cfg_action,bubble,cfg_rss_key);
    if(rc!=7) $fatal(1,"BAD_CONFIG");
    cfg_op=j;cfg_index=i;cfg_enable=bubble;cfg_valid=1;
    s_axis_tvalid=0;
    tick();cfg_valid=0;configs=configs+1;
    if(cfg_op==3) default_shadow=cfg_action;
   end else if(cmd==1) begin
    rc=$fscanf(fd,"%d %d %d %d %h %h %d %d %h %d %h %d %d %d %h %d",
      id,n,mode,abort_kind,ec32,ec64,emm,ecerr,eheader,elen,ehash,erv,ehit,eidx,eaction,deferred_cfg);
    if(rc!=16 || n>2048 || n<1) $fatal(1,"BAD_PACKET");
    if(deferred_cfg) begin
     rc=$fscanf(fd,"%d %d %h %h %h %d %h",j,i,pending_value,pending_mask,pending_action,bubble,pending_key);
     if(rc!=7) $fatal(1,"BAD_DEFERRED_CONFIG");
     pending_op=j;pending_index=i;pending_enable=bubble;
    end
    for(i=0;i<n;i=i+1) begin
     rc=$fscanf(fd,"%h %h %h %h %h",bd[i],bk[i],bc[i],b32[i],b64[i]);
     if(rc!=5) $fatal(1,"BAD_BEAT");
    end
    active=1;sent=0;received=0;crc_received=0;meta_received=0;bubble=0;
    first_meta=0;final_edge=-1;deadline=cycle+n*8+1400;
    // Offer a real first beat during an idle no-op configuration, then keep
    // that beat asserted unchanged until its own ingress handshake.
    s_axis_tvalid=1;s_axis_tdata=bd[0];s_axis_tkeep=bk[0];s_axis_tlast=(n==1);
    s_check_enable=bc[0];s_expected_crc32c=b32[0];s_expected_crc64_nvme=b64[0];
    cfg_valid=1;cfg_op=3;cfg_action=default_shadow;
    #1;if(s_axis_tready!==0 || cfg_ready!==1) $fatal(1,"CONFIG_PRIORITY");
    tick();cfg_valid=0;configs=configs+1;priority_count=priority_count+1;
    if(sent!=0) $fatal(1,"CONFIG_PRIORITY_INGRESS_TRANSFER");
    if(deferred_cfg) begin
     cfg_op=pending_op;cfg_index=pending_index;cfg_value=pending_value;
     cfg_mask=pending_mask;cfg_action=pending_action;cfg_enable=pending_enable;cfg_rss_key=pending_key;
    end
    while ((received<n || !crc_received || !meta_received) && cycle<deadline) begin
     set_ready();
     if (bubble>0) begin s_axis_tvalid=0;bubble=bubble-1;end
     else if (sent<n) begin
      s_axis_tvalid=1;s_axis_tdata=bd[sent];s_axis_tkeep=bk[sent];
      s_axis_tlast=(sent==n-1);s_check_enable=bc[sent];
      s_expected_crc32c=b32[sent];s_expected_crc64_nvme=b64[sent];
     end else s_axis_tvalid=0;
     cfg_valid=deferred_cfg && sent>0;
     tick();
     if ((abort_kind==1 && sent>0 && sent<n) ||
         (abort_kind==2 && final_edge>=0 && cycle-final_edge==300) ||
         (abort_kind==3 && first_meta)) begin
      report($sformatf("ABORT %0d %0d %0d %0d",id,abort_kind,sent,received));
      reset_dut(); received=n;crc_received=1;meta_received=1;
     end
    end
    if(cycle>=deadline) $fatal(1,"LOST_RESULT id=%0d",id);
    s_axis_tvalid=0;
    if(!abort_kind) begin
     report($sformatf("DONE %0d %0d %h %h %h %0d %h %0d %0d %0d %h",
       id,n,observed_c32,observed_c64,observed_header,observed_length,
       observed_hash,observed_rss,observed_hit,observed_index,observed_action));
     packet_count=packet_count+1;
    end
    active=0;
    if(deferred_cfg && !abort_kind) begin
     if(cfg_ready!==1 || cfg_valid!==1) $fatal(1,"DEFERRED_CONFIG_NOT_RELEASED");
     tick();cfg_valid=0;configs=configs+1;deferred_count=deferred_count+1;
     if(cfg_op==3) default_shadow=cfg_action;
    end
    cfg_valid=0;tick();tick();
   end else if(cmd==2) reset_dut();
   else $fatal(1,"UNKNOWN_COMMAND");
  end
 end
 s_axis_tvalid=0;cfg_valid=0;m_axis_tready=1;m_crc_ready=1;m_meta_ready=1;
 repeat(20) tick();
 report($sformatf("COUNTS %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d",packet_count,beat_count,
   stalls_b,stalls_c,stalls_m,simultaneous,resets,configs,ingress_bubbles,deferred_count,priority_count));
 $fclose(transcript);
 $finish;
end
endmodule
""".replace("@WIDTH@", str(width))


def leaf_bench(kind):
    if kind == "rss":
        declarations = """
reg in_valid=0,in_eligible=0;
reg [295:0] in_tuple=0;
reg [8:0] in_tuple_bits=0;
reg [327:0] in_key=0;
wire out_valid,out_eligible;
wire [31:0] out_hash;
reg [31:0] expected;
integer eligible,bits;
furnace_rss_toeplitz dut(.*);
"""
        operation = """
rc=$fscanf(fd,"%h %d %d %h %h",in_tuple,bits,eligible,in_key,expected);
if(rc!=5) $fatal(1,"BAD_RSS_VECTOR");
in_tuple_bits=bits;in_eligible=eligible;in_valid=1;tick();in_valid=0;
if(out_valid!==0) $fatal(1,"EARLY_RSS");
for(j=1;j<=296;j=j+1) begin
 tick();
 if(j<296 && out_valid!==0) $fatal(1,"EARLY_RSS");
end
if({out_valid,out_hash,out_eligible} !== {1'b1,expected,1'(eligible)})
 $fatal(1,"RSS_MISMATCH case=%0d actual=%h expected=%h",count,out_hash,expected);
$display("LEAF %0d %h %0d",count,out_hash,out_eligible);
tick();if(out_valid!==0) $fatal(1,"DUPLICATE_RSS");
"""
        zero = "{out_valid,out_hash,out_eligible}"
    else:
        declarations = """
reg cfg_write=0,cfg_clear=0,cfg_enable=0,in_valid=0;
reg [5:0] cfg_index=0;
reg [511:0] cfg_value=0,cfg_mask=0,in_key=0;
reg [31:0] cfg_action=0,in_default_action=0;
wire out_valid,out_hit;
wire [5:0] out_index;
wire [31:0] out_action;
integer index,en,hit,win;
reg [31:0] expected;
furnace_classifier64 dut(.*);
"""
        operation = """
if(cmd==0) begin
 rc=$fscanf(fd,"%d %h %h %h %d",index,cfg_value,cfg_mask,cfg_action,en);
 if(rc!=5) $fatal(1,"BAD_RULE_VECTOR");
 cfg_index=index;cfg_enable=en;cfg_write=1;tick();cfg_write=0;
end else if(cmd==2) begin cfg_clear=1;tick();cfg_clear=0; end
else begin
 rc=$fscanf(fd,"%h %h %d %d %h",in_key,in_default_action,hit,win,expected);
 if(rc!=5) $fatal(1,"BAD_CLASSIFIER_VECTOR");
 in_valid=1;tick();in_valid=0;
 if(out_valid!==0) $fatal(1,"EARLY_CLASSIFIER");
 for(j=1;j<=639;j=j+1) begin
  tick();
  if(j<639 && out_valid!==0) $fatal(1,"EARLY_CLASSIFIER");
 end
 if({out_valid,out_hit,out_index,out_action} !== {1'b1,1'(hit),6'(win),expected})
  $fatal(1,"CLASSIFIER_MISMATCH case=%0d actual=%h expected=%h",count,
    {out_hit,out_index,out_action},{1'(hit),6'(win),expected});
 $display("LEAF %0d %0d %0d %h",count,out_hit,out_index,out_action);
 tick();if(out_valid!==0) $fatal(1,"DUPLICATE_CLASSIFIER");
 count=count+1;
end
"""
        zero = "{out_valid,out_hit,out_index,out_action}"
    return ("""
`timescale 1ns/1ps
module tb;
reg clk=0,rst_n;
integer fd,rc,cmd,j,count=0;
""" + declarations + """
task automatic tick;
begin #5;clk=1;#1;#4;clk=0;end endtask
always @(posedge clk or negedge clk) if(!rst_n && $time>0)
 if(@ZERO@ !== 0) $fatal(1,"LEAF_RESET");
initial begin
 rst_n=0;
`ifndef VERILATOR
 #0;if(@ZERO@ !== 0) $fatal(1,"LEAF_RESET_TIME_ZERO");
`else
 #1;if(@ZERO@ !== 0) $fatal(1,"LEAF_RESET_TIME_ZERO");
`endif
 tick();tick();rst_n=1;
 fd=$fopen("stimulus.txt","r");if(!fd) $fatal(1,"NO_STIMULUS");
 while(!$feof(fd)) begin
  rc=$fscanf(fd,"%d",cmd);
  if(rc==1) begin
""" + operation + ("""
 count=count+1;
""" if kind == "rss" else "") + """
  end
 end
 $display("LEAF_COUNT %0d",count);$finish;
end
endmodule
""").replace("@ZERO@", zero)
