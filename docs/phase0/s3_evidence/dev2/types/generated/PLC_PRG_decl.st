PROGRAM PLC_PRG
VAR
    (* Deterministic demo for AHU-01 *)
    StartCommand : BOOL := FALSE;
    StopCommand : BOOL := FALSE;
    FanCommand : BOOL := FALSE;
    FanRunning : BOOL := FALSE;
    FanFault : BOOL := FALSE;
    SupplyTemp : REAL := 21.0;
    Setpoint : REAL := 22.0;
    FanSpeed : REAL := 50.0;
    HeatingValve : REAL := 0.0;
    TestCoil : BOOL := FALSE;
    TestDiscreteInput : BOOL := TRUE;
    TestWordRead : WORD := 16#A55A;
    TestWordWrite : WORD := 16#0000;
    TestInt16Read : INT := -1234;
    TestInt16Write : INT := 0;
    TestUInt16Read : UINT := 1234;
    TestUInt16Write : UINT := 0;
    TestReal32Read : REAL := 21.5;
    TestReal32Write : REAL := 0.0;
    (* Modbus TCP image (16-bit words, mapped to Modbus_TCP_Server I/O) *)
    Mb_Command : WORD; (* HR0 Command: bit0=StartCommand, bit1=StopCommand *)
    Mb_TestInt16Write : WORD; (* HR1 TestInt16Write INT16 WRITE *)
    Mb_TestReal32Write_W0 : WORD; (* HR2 TestReal32Write REAL32 memory word 0 *)
    Mb_TestReal32Write_W1 : WORD; (* HR3 TestReal32Write REAL32 memory word 1 *)
    p_TestReal32Write : POINTER TO ARRAY[0..1] OF WORD;
    Mb_TestUInt16Write : WORD; (* HR4 TestUInt16Write UINT16 WRITE *)
    Mb_Status : WORD; (* IR0 Status: bit0=FanCommand, bit1=FanRunning, bit2=FanFault *)
    Mb_TestInt16Read : WORD; (* IR1 TestInt16Read INT16 READ *)
    Mb_TestReal32Read_W0 : WORD; (* IR2 TestReal32Read REAL32 memory word 0 *)
    Mb_TestReal32Read_W1 : WORD; (* IR3 TestReal32Read REAL32 memory word 1 *)
    p_TestReal32Read : POINTER TO ARRAY[0..1] OF WORD;
    Mb_TestUInt16Read : WORD; (* IR4 TestUInt16Read UINT16 READ *)
END_VAR
