PROGRAM PLC_PRG
VAR
    (* Deterministic demo for PUMP-DEMO: PUMP-01 (PUMP) *)
    StartCommand : BOOL := FALSE;
    StopCommand : BOOL := FALSE;
    PumpRunning : BOOL := FALSE;
    PumpFault : BOOL := FALSE;
    PumpState : INT := 0;
    PumpSpeed : REAL := 0.0;
    Pressure : REAL := 0.0;
    (* Modbus TCP image (16-bit words, mapped to Modbus_TCP_Server I/O) *)
    Mb_Pressure_W0 : WORD; (* IR0 Pressure REAL32 memory word 0 *)
    Mb_Pressure_W1 : WORD; (* IR1 Pressure REAL32 memory word 1 *)
    p_Pressure : POINTER TO ARRAY[0..1] OF WORD;
    Mb_PumpSpeed_W0 : WORD; (* IR2 PumpSpeed REAL32 memory word 0 *)
    Mb_PumpSpeed_W1 : WORD; (* IR3 PumpSpeed REAL32 memory word 1 *)
    p_PumpSpeed : POINTER TO ARRAY[0..1] OF WORD;
    Mb_PumpState : WORD; (* IR4 PumpState INT16 READ *)
    Mb_StartCommand : BOOL; (* C144 StartCommand = HR9 PLC bit 8 *)
    Mb_StopCommand : BOOL; (* C145 StopCommand = HR9 PLC bit 9 *)
    Mb_PumpFault : BOOL; (* DI144 PumpFault = IR9 PLC bit 8 *)
    Mb_PumpRunning : BOOL; (* DI145 PumpRunning = IR9 PLC bit 9 *)
END_VAR
