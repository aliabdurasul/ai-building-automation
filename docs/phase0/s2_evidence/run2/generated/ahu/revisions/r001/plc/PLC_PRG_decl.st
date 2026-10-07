PROGRAM PLC_PRG
VAR
    (* Deterministic demo for AHU-DEMO: AHU-01 (AHU) *)
    StartCommand : BOOL := FALSE;
    StopCommand : BOOL := FALSE;
    FanCommand : BOOL := FALSE;
    FanRunning : BOOL := FALSE;
    FanFault : BOOL := FALSE;
    SupplyTemp : REAL := 21.0;
    Setpoint : REAL := 22.0;
    FanSpeed : REAL := 50.0;
    HeatingValve : REAL := 0.0;
    TestReal32Read : REAL := 21.5;
    (* Modbus TCP image (16-bit words, mapped to Modbus_TCP_Server I/O) *)
    Mb_Command : WORD; (* HR0 Command: bit0=StartCommand, bit1=StopCommand *)
    Mb_Setpoint_W0 : WORD; (* HR1 Setpoint REAL32 memory word 0 *)
    Mb_Setpoint_W1 : WORD; (* HR2 Setpoint REAL32 memory word 1 *)
    p_Setpoint : POINTER TO ARRAY[0..1] OF WORD;
    Mb_Setpoint_W0_prev : WORD;
    Mb_Setpoint_W1_prev : WORD;
    Mb_Status : WORD; (* IR0 Status: bit0=FanCommand, bit1=FanRunning, bit2=FanFault *)
    Mb_FanSpeed_W0 : WORD; (* IR1 FanSpeed REAL32 memory word 0 *)
    Mb_FanSpeed_W1 : WORD; (* IR2 FanSpeed REAL32 memory word 1 *)
    p_FanSpeed : POINTER TO ARRAY[0..1] OF WORD;
    Mb_SupplyTemp_W0 : WORD; (* IR3 SupplyTemp REAL32 memory word 0 *)
    Mb_SupplyTemp_W1 : WORD; (* IR4 SupplyTemp REAL32 memory word 1 *)
    p_SupplyTemp : POINTER TO ARRAY[0..1] OF WORD;
    Mb_TestReal32Read_W0 : WORD; (* IR5 TestReal32Read REAL32 memory word 0 *)
    Mb_TestReal32Read_W1 : WORD; (* IR6 TestReal32Read REAL32 memory word 1 *)
    p_TestReal32Read : POINTER TO ARRAY[0..1] OF WORD;
    Mb_FanRunning : BOOL; (* DI144 FanRunning = IR9 PLC bit 8 *)
END_VAR
