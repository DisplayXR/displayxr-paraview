"""Write the demo and test datasets for ParaView Glance in the DisplayXR Browser.

Run with ParaView's own Python (no other dependencies):
    pvpython web/tools/make_data.py [out_dir]

Writes:
    disk_out_ref.vtp   ParaView's example disk_out_ref.ex2, surface with Temp/Pres point data
    depth_spheres.vtp  three spheres at known depths along +z (for disparity measurement)
"""
import os
import sys

from vtkmodules.vtkFiltersCore import vtkAppendPolyData
from vtkmodules.vtkFiltersGeometry import vtkGeometryFilter
from vtkmodules.vtkFiltersSources import vtkSphereSource
from vtkmodules.vtkIOExodus import vtkExodusIIReader
from vtkmodules.vtkIOXML import vtkXMLPolyDataWriter
from vtkmodules.vtkFiltersCore import vtkPolyDataNormals
from vtkmodules.vtkFiltersCore import vtkTriangleFilter


def write(poly, path):
    w = vtkXMLPolyDataWriter()
    w.SetFileName(path)
    w.SetInputData(poly)
    w.SetDataModeToBinary()
    w.SetCompressorTypeToZLib()
    w.Write()
    print("wrote", path, poly.GetNumberOfPoints(), "points")


def disk(out_dir):
    pv_root = os.path.dirname(os.path.dirname(sys.executable))
    src = os.path.join(pv_root, "examples", "disk_out_ref.ex2")
    r = vtkExodusIIReader()
    r.SetFileName(src)
    r.UpdateInformation()
    for i in range(r.GetNumberOfPointResultArrays()):
        r.SetPointResultArrayStatus(r.GetPointResultArrayName(i), 1)
    r.Update()
    from vtkmodules.vtkFiltersGeometry import vtkCompositeDataGeometryFilter
    g = vtkCompositeDataGeometryFilter()
    g.SetInputConnection(r.GetOutputPort())
    t = vtkTriangleFilter()
    t.SetInputConnection(g.GetOutputPort())
    n = vtkPolyDataNormals()
    n.SetInputConnection(t.GetOutputPort())
    n.Update()
    write(n.GetOutput(), os.path.join(out_dir, "disk_out_ref.vtp"))


def spheres(out_dir):
    # Centres on the z axis at -1, 0, +1 (radius 0.15), offset in x so they don't overlap
    # in the default view down -z: left = far, middle = mid, right = near.
    app = vtkAppendPolyData()
    for x, z in ((-0.6, -1.0), (0.0, 0.0), (0.6, 1.0)):
        s = vtkSphereSource()
        s.SetCenter(x, 0.0, z)
        s.SetRadius(0.15)
        s.SetThetaResolution(48)
        s.SetPhiResolution(24)
        app.AddInputConnection(s.GetOutputPort())
    app.Update()
    g = vtkGeometryFilter()
    g.SetInputData(app.GetOutput())
    g.Update()
    write(g.GetOutput(), os.path.join(out_dir, "depth_spheres.vtp"))


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(out, exist_ok=True)
    disk(out)
    spheres(out)
