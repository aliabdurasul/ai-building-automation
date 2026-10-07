PROGRAM PLC_PRG
VAR
    (* Deterministic demo for AHU-SEQ: AHU-01 (AHU) *)
    StartCommand : BOOL := FALSE;
    StopCommand : BOOL := FALSE;
    FanCommand : BOOL := FALSE;
    FanRunning : BOOL := FALSE;
    FanFault : BOOL := FALSE;
    DamperCommand : BOOL := FALSE;
    DamperOpen : BOOL := FALSE;
    FanFailure : BOOL := FALSE;
    DamperFailure : BOOL := FALSE;
    DamperFault : BOOL := FALSE;
    AhuAlarm : BOOL := FALSE;
    AhuState : INT := 0;
    StateTrace : WORD := 16#0000;
    SequenceStarts : UINT := 0;
    SequenceStops : UINT := 0;
    StartPrev : BOOL := FALSE;
    StopPrev : BOOL := FALSE;
    NowMs : UDINT := 0;
    StateEntryMs : UDINT := 0;
    SupplyTemp : REAL := 21.0;
    Setpoint : REAL := 22.0;
    HeatingValve : REAL := 0.0;
    (* Modbus TCP image (16-bit words, mapped to Modbus_TCP_Server I/O) *)
    Mb_Command : WORD; (* HR0 Command: bit0=StartCommand, bit1=StopCommand *)
    Mb_Setpoint_W0 : WORD; (* HR1 Setpoint REAL32 memory word 0 *)
    Mb_Setpoint_W1 : WORD; (* HR2 Setpoint REAL32 memory word 1 *)
    p_Setpoint : POINTER TO ARRAY[0..1] OF WORD;
    Mb_Setpoint_W0_prev : WORD;
    Mb_Setpoint_W1_prev : WORD;
    Mb_Status : WORD; (* IR0 Status: bit0=FanCommand, bit1=FanRunning, bit2=FanFault *)
    Mb_AhuState : WORD; (* IR1 AhuState INT16 READ *)
    Mb_HeatingValve_W0 : WORD; (* IR2 HeatingValve REAL32 memory word 0 *)
    Mb_HeatingValve_W1 : WORD; (* IR3 HeatingValve REAL32 memory word 1 *)
    p_HeatingValve : POINTER TO ARRAY[0..1] OF WORD;
    Mb_SequenceStarts : WORD; (* IR4 SequenceStarts UINT16 READ *)
    Mb_SequenceStops : WORD; (* IR5 SequenceStops UINT16 READ *)
    Mb_StateTrace : WORD; (* IR6 StateTrace WORD READ *)
    Mb_SupplyTemp_W0 : WORD; (* IR7 SupplyTemp REAL32 memory word 0 *)
    Mb_SupplyTemp_W1 : WORD; (* IR8 SupplyTemp REAL32 memory word 1 *)
    p_SupplyTemp : POINTER TO ARRAY[0..1] OF WORD;
    Mb_AhuAlarm : BOOL; (* DI144 AhuAlarm = IR9 PLC bit 8 *)
    Mb_DamperCommand : BOOL; (* DI145 DamperCommand = IR9 PLC bit 9 *)
    Mb_DamperFault : BOOL; (* DI146 DamperFault = IR9 PLC bit 10 *)
    Mb_DamperOpen : BOOL; (* DI147 DamperOpen = IR9 PLC bit 11 *)
    Mb_FanRunning : BOOL; (* DI148 FanRunning = IR9 PLC bit 12 *)
END_VAR
