# CubeSatSim HIL

The HIL tools run on the control PC and communicate with the Raspberry Pi over SSH. 

**PROBE** 
Acts as a read-only probe: it establishes that(/if) the remote connection and 
the current CubeSatSim runtime are observable w/o doing any sensor injection

Run from the repository root:

```sh:
python3 hil/probe.py --host cubesatsim.local --user pi

#or

python3 hil/probe.py --host cubesatsim.local --user pi --json   #for machine-readable output
```

The probe checks the `cubesatsim` and `transmit` services, current mode,
simulation flags, I2C device nodes, and payload UART availability. It does not
restart services, change configuration, access GPIO, or transmit RF.



**INVENTORY (DiSCOVERY)**
Collect the "inventory" with:

```sh
python3 hil/inventory.py --host cubesatsim.local --user pi

#or 

python3 hil/inventory.py --host cubesatsim.local --user pi --json   #for machine-readable output
```

read-only and discovery-style without assuming Bus 1/3, a fixed list of INA219 channels, or a 
particula payload. The report always includes raw command output so an unknown component
can be investigated without changing the discovery engine.


CubeSatSim-specific checks are optional adapters (run with the tag `--adapters`):

The adapters run `config -v` and `config -p` only when requested. A missing
adapter dependency or optional component is reported as unavailable and does
not invalidate tbe generic discovery