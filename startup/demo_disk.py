# ParaView startup script for the DisplayXR demo: loads the XRInterface plug-in
# and the disk_out_ref example (flow around a heated disk), framed for a desk 3D display.
import os
import sys

from paraview.simple import *

# <install>/bin/paraview.exe -> <install>/examples
examples = os.environ.get("DXR_PV_EXAMPLES") or os.path.join(os.path.dirname(os.path.dirname(sys.executable)), "examples")
disk = ExodusIIReader(registrationName="disk_out_ref.ex2", FileName=os.path.join(examples, "disk_out_ref.ex2"))
disk.PointVariables = ["Temp", "V", "Pres"]

view = GetActiveViewOrCreate("RenderView")
# Mid-grey gradient instead of ParaView's dark backdrop: bright edges on near-black ghost on the lens.
view.BackgroundColorMode = "Gradient"
view.UseColorPaletteForBackground = 0
view.Background = [0.32, 0.34, 0.38]
view.Background2 = [0.16, 0.17, 0.2]
view.OrientationAxesVisibility = 0

# Half the disk's housing, so the flow inside stays visible.
clip = Clip(registrationName="Housing", Input=disk)
clip.ClipType = "Plane"
clip.ClipType.Normal = [1.0, 0.0, 0.0]
housing = Show(clip, view)
housing.Representation = "Surface"
ColorBy(housing, ("POINTS", "Temp"))
housing.Opacity = 0.35

lines = StreamTracer(registrationName="Flow", Input=disk, SeedType="Point Cloud")
lines.Vectors = ["POINTS", "V"]
lines.SeedType.Center = [0.0, 0.0, 0.07]
lines.SeedType.Radius = 2.5
lines.SeedType.NumberOfPoints = 150
lines.MaximumStreamlineLength = 20.0
tubes = Tube(registrationName="FlowTubes", Input=lines)
tubes.Radius = 0.06
flow = Show(tubes, view)
ColorBy(flow, ("POINTS", "Temp"))
flow.SetScalarBarVisibility(view, False)
housing.SetScalarBarVisibility(view, False)

view.CameraPosition = [-22.0, 9.0, 14.0]
view.CameraFocalPoint = [0.0, 0.0, 0.0]
view.CameraViewUp = [0.0, 0.0, 1.0]
ResetCamera(view)
Render(view)

if os.environ.get("DXR_PV_DEV_INBOX"):
    import dev_inbox

    dev_inbox.install(os.environ["DXR_PV_DEV_INBOX"])
