PROGRAM PLC_PRG
VAR
    (* Deterministic demo for BMS-DEMO: AHU-01 (AHU), PUMP-01 (PUMP) *)
    StartCommand : BOOL := FALSE;
    StopCommand : BOOL := FALSE;
    FanCommand : BOOL := FALSE;
    FanRunning : BOOL := FALSE;
    FanFault : BOOL := FALSE;
    SupplyTemp : REAL := 21.0;
    Setpoint : REAL := 22.0;
    HeatingValve : REAL := 0.0;
    PUMP01_StartCommand : BOOL := FALSE;
    PUMP01_StopCommand : BOOL := FALSE;
    PumpRunning : BOOL := FALSE;
    PumpFault : BOOL := FALSE;
    PumpState : INT := 0;
    PumpSpeed : REAL := 0.0;
    Pressure : REAL := 0.0;
    (* Modbus TCP image (16-bit words, mapped to Modbus_TCP_Server I/O) *)
    Mb_Command : WORD; (* HR0 Command: bit0=StartCommand, bit1=StopCommand *)
    Mb_Setpoint_W0 : WORD; (* HR1 Setpoint REAL32 memory word 0 *)
    Mb_Setpoint_W1 : WORD; (* HR2 Setpoint REAL32 memory word 1 *)
    p_Setpoint : POINTER TO ARRAY[0..1] OF WORD;
    Mb_Setpoint_W0_prev : WORD;
    Mb_Setpoint_W1_prev : WORD;
    Mb_Status : WORD; (* IR0 Status: bit0=FanCommand, bit1=FanRunning, bit2=FanFault *)
    Mb_Pressure_W0 : WORD; (* IR1 Pressure REAL32 memory word 0 *)
    Mb_Pressure_W1 : WORD; (* IR2 Pressure REAL32 memory word 1 *)
    p_Pressure : POINTER TO ARRAY[0..1] OF WORD;
    Mb_PumpSpeed_W0 : WORD; (* IR3 PumpSpeed REAL32 memory word 0 *)
    Mb_PumpSpeed_W1 : WORD; (* IR4 PumpSpeed REAL32 memory word 1 *)
    p_PumpSpeed : POINTER TO ARRAY[0..1] OF WORD;
    Mb_PumpState : WORD; (* IR5 PumpState INT16 READ *)
    Mb_SupplyTemp_W0 : WORD; (* IR6 SupplyTemp REAL32 memory word 0 *)
    Mb_SupplyTemp_W1 : WORD; (* IR7 SupplyTemp REAL32 memory word 1 *)
    p_SupplyTemp : POINTER TO ARRAY[0..1] OF WORD;
    Mb_PUMP01_StartCommand : BOOL; (* C144 PUMP01_StartCommand = HR9 PLC bit 8 *)
    Mb_PUMP01_StopCommand : BOOL; (* C145 PUMP01_StopCommand = HR9 PLC bit 9 *)
    Mb_FanRunning : BOOL; (* DI144 FanRunning = IR9 PLC bit 8 *)
    Mb_PumpFault : BOOL; (* DI145 PumpFault = IR9 PLC bit 9 *)
    Mb_PumpRunning : BOOL; (* DI146 PumpRunning = IR9 PLC bit 10 *)
END_VAR
