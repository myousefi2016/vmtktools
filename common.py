import vtk
import numpy as np
import sys
import re
from os import path
import math
from subprocess import check_output, STDOUT

# Global names
radiusArrayName = 'MaximumInscribedSphereRadius'
parallelTransportNormalsArrayName = 'ParallelTransportNormals'
AbscissasArrayName = 'Abscissas'
divergingRatioToSpacingTolerance = 2.0
distance = vtk.vtkMath.Distance2BetweenPoints
interpolationHalfSize = 3
polyBallImageSize = [200, 200, 200]


def ReadPolyData(filename):
    reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(filename)
    reader.Update()
    return reader.GetOutput()


def WritePolyData(input, filename):
    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(filename)
    writer.SetInput(input)
    writer.Write()


def get_curvilinear_coordinate(line):
    curv_coor = np.zeros(line.GetNumberOfPoints())
    for i in range(line.GetNumberOfPoints() - 1):
        pnt1 = np.asarray(line.GetPoints().GetPoint(i))
        pnt2 = np.asarray(line.GetPoints().GetPoint(i+1))
        curv_coor[i+1] = np.sum(np.sqrt((pnt1 - pnt2)**2)) + curv_coor[i]

    return curv_coor


def get_array(arrayName, line, k=1):
    array = np.zeros((line.GetNumberOfPoints(), k))
    vtkArray = line.GetPointData().GetArray(arrayName)
    if k == 1:
        getData = line.GetPointData().GetArray(arrayName).GetTuple1
    elif k == 2:
        getData = line.GetPointData().GetArray(arrayName).GetTuple2
    elif k ==3:
        getData = line.GetPointData().GetArray(arrayName).GetTuple3

    for i in range(line.GetNumberOfPoints()):
        array[i,:] = getData(i)

    return array


def get_vtk_array(name, comp, num):
    array = vtk.vtkDoubleArray()
    array.SetNumberOfComponents(comp)
    array.SetNumberOfTuples(num)
    for i in range(comp):
        array.FillComponent(i, 0.0)
    array.SetName(name)
    return array


def get_locator(centerline):
    locator = vtk.vtkPointLocator()
    locator.SetDataSet(centerline)
    locator.BuildLocator()
    return locator


def remove_distant_points(voronoi, centerline):
    N = voronoi.GetNumberOfPoints()
    newVoronoi = vtk.vtkPolyData()
    cellArray = vtk.vtkCellArray()
    points = vtk.vtkPoints()
    radiusArray = get_vtk_array(radiusArrayName, 1, N)
    
    locator = get_locator(centerline)
    get_data = voronoi.GetPointData().GetArray(radiusArrayName).GetTuple1
    limit = get_data(0)*100

    count = 0
    for i in range(N):
        point = voronoi.GetPoint(i)
        cl_point = centerline.GetPoint(locator.FindClosestPoint(point))
        dist = math.sqrt(distance(point, cl_point))
        if dist > get_data(i)*3 or get_data(i) > limit:
            print dist, get_data(i)*3, point, cl_point
            count += 1
            print "Removed a point from the voronoi diagram", count
            continue
        points.InsertNextPoint(point)
        cellArray.InsertNextCell(1)
        cellArray.InsertCellPoint(i)
        value = get_data(i)
        radiusArray.SetTuple1(i, value)

    newVoronoi.SetPoints(points)
    newVoronoi.SetVerts(cellArray)
    newVoronoi.GetPointData().AddArray(radiusArray)

    return newVoronoi


def success(text):
    if not "error: " in text.lower():
        return True, ""
    else:
        error_message = re.search(r'error: (.*)', text.lower()).groups()[0]
        return False, error_message


def makeCenterlineSections(isurface, ifile, ofile, recompute=False):
    if not path.exists(ifile):
        print "The input file: %s does not exsists!" % ifile
        sys.exit(0)

    if not path.exists(isurface):
        print "The input file: %s does not exsists!" % isurface
        sys.exit(0)

    if not path.exists(ofile) or recompute:
        a = check_output(("vmtkcenterlinesections -ifile %s -centerlinesfile %s" + \
                    " -ocenterlinesfile %s") \
                          % (isurface, ifile, ofile),
                          stderr=STDOUT, shell=True)
        status, text = success(a)
        if not status:
            print ("Something went wrong when making the centerline sections. Error" + \
                  "message:\n%s") % text
            sys.exit(0)

    return ReadPolyData(ofile)


def makeCenterline(ifile, ofile, length=1, it=100, factor=0.1, in_out=None,
                   smooth=True, resampling=True, recompute=False):
    """A general centerline command. If a centerline file with the same file
    name alread exists, then the file i just read. To overwrite this set
    recompute to True. If recomputed is to True then it uses the exsisting points
    from the old centerline file and no interaction with the interface is
    needed. Further on one can choose witch points you want to include by
    giving in_out. The first element in the list is the source point, and if -1
    is given, is chooses the old inlet, else it chooses outletX, where X is the
    outlet ID.
    
    it an int, number of iterations in the smoothening
    factor a float, the smoothening factor
    length a float in (0,1], is the resampling factor
    smooth is a boolean that could turn on/off smoothening
    resampling is a boolean that could turn in/off resampling
    in_out a list of outlet/inlet points that should be uses when recompute"""

    # Check if ifile exsists
    if not path.exists(ifile):
        print "The input file: %s does not exsists!" % ifile
        sys.exit(0)

    # Check if it already exsists or if it is to be recomputed
    if not path.exists(ofile) or recompute:
        # If recomputed use the old source and target points
        basedir = path.sep.join(path.join(ifile.split(path.sep)[:-2]))
        parameters = getParameters(basedir)
        if parameters.has_key("inlet"):
            if in_out is None:
                inlet = parameters["inlet"]
            else:
                inlet = parameters["inlet"] if in_out[0] == -1 else parameters["outlet%s"%in_out[0]]
            source = " -seedselector pointlist -sourcepoints %s %s %s -targetpoints " \
                     % (inlet[0], inlet[1], inlet[2])

            if in_out is not None:
                points_ = [parameters["outlet%s"%i] for i in in_out[1:]]
            else:
                out = [k for k in parameters.keys() if "outlet" in k]
                out.sort()
                points_ = [parameters[p] for p in out]

            points = []
            for p in points_:
                points += [str(p[0]), str(p[1]), str(p[2])]

            text = " ".join(points)
            source += text
            store_points = False


        else:
            store_points = True
            source = ""

        # Add smoothing
        if smooth:
            smooth = " --pipe vmtkcenterlinesmoothing -iterations %s -factor %s" % (it, factor)
        else:
            smooth = ""

        # Add resampling
        resampling = " -resampling 1 -resamplingstep %s" % length if resampling else ""

        # Execute command
        a = check_output(("vmtkcenterlines -ifile %s%s%s%s -ofile %s") % \
                        (ifile, source, resampling, smooth, ofile), 
                        stderr=STDOUT, shell=True)
        # Check the success of the command, vmtk could fail without crashing
        status, text = success(a)
        if not status:
            print ("Something went wrong when making the centerline. Error" + \
                   " message:\n%s") % text
            sys.exit(0)

        # If the points are not already storted, do it now
        if store_points:
            centerline = ReadPolyData(ofile)
            end_points = []
            start_point = []
            for i in range(centerline.GetNumberOfLines()):
                tmp_line = ExtractSingleLine(centerline, i)
                tmp_N = tmp_line.GetNumberOfPoints()
                parameters["outlet%s" % i] = tmp_line.GetPoint(tmp_N - 1)
            parameters["inlet"] = tmp_line.GetPoint(0)
            writeParameters(parameters, basedir)
    
    return ReadPolyData(ofile)


def CenterlineAttribiute(line, remove=True, filename=None, smooth=False,
                         it=300, factor=0.1):
    if filename is None:
        filename = "tmp_cl.vtp"
        WritePolyData(line, FileName)

    command = ('vmtkcenterlineattributes -ifile %s --pipe vmtkcenterlinegeometry ' + \
               '-ofile %s') % (filename, filename)
    if smooth:
        command += ' -smoothing 1 iterations %s -factor %s -outputsmoothd 1' %
                   (it, factor)
    else:
        command += ' -smoothing 0'
    a = subprocess.check_output(command, stderr=subprocess.STDOUT, shell=True)
    status, text = success(a)

    if not status:
        print "smoething went wront when finding the attributes for the centerline"
        print text
        sys.exit(0)

    line = ReadPolyData(tmpFileName)
    if remove:
        subprocess.check_output('rm ' + tmpFileName, stderr=subprocess.STDOUT, shell=True)
    return line


def makeVoronoi(ifile, ofile, recompute=False):
    if not path.exists(ifile):
        print "The input file does not exsists!"
        sys.exit(0)

    if not path.exists(ofile) or recompute:
        a = check_output(("vmtkdelaunayvoronoi -ifile %s -removesubresolution 1 " + \
                    "-voronoidiagramfile %s") % (ifile, ofile), stderr=STDOUT, shell=True)
        status, text = success(a)
        if not status:
            print ("Something went wrong when making the voronoi diagram. Error" + \
                  "message:\n%s") % text
            sys.exit(0)

    return ReadPolyData(ofile)


def create_vtk_array(values, name, k=1):
    vtkArray = get_vtk_array(name, k, values.shape[0])

    if k == 1:
        for i in range(values.shape[0]):
            vtkArray.SetTuple1(i, values[i])
    elif k == 2:
        for i in range(values.shape[0]):
            vtkArray.SetTuple2(i, values[i,0], values[i,1])
    elif k == 3:
        for i in range(values.shape[0]):
            vtkArray.SetTuple3(i, values[i,0], values[i,1], values[i,2])

    return vtkArray


def GramSchmidt(V):
    V = 1.0 * V
    U = np.copy(V)

    def proj(u, v):
        return u * np.dot(v,u) / np.dot(u,u)

    for i in xrange(1, V.shape[1]):
        for j in xrange(i):
            U[:,i] -= proj(U[:,j], V[:,i])

    # normalize column
    den=(U**2).sum(axis=0)**0.5
    E = U/den
    return E


def getParameters(folder):
    f = open(path.join(folder, "manifest.txt"), "r")
    text = f.read()
    f.close()
    text = text.split("\n")
    
    data = {}
    for par in text:
        if par != "":
            key, value = par.split(": ")
            try:
                data[key] = eval(value)
            except:
                data[key] = value

    return data


def writeParameters(data, folder):
    """Assumes a dictionary and consistent naming for each run"""
    parameters = getParameters(folder)
    for key, value in data.iteritems():
        parameters[key] = value

    text = ["%s: %s" % (k, v) for k, v in parameters.iteritems()]
    text = "\n".join(text)
    
    f = open(path.join(folder, "manifest.txt"), "w")
    f.write(text)
    f.close()


def read_dat(filename):
    f = open(filename, "r")
    text = f.readline()
    
    header = text.split(" ")
    header[-1] = header[-1][:-2]

    lines = f.readlines()
    f.close()

    data = np.zeros((len(lines), len(header)))
    col_len = len(lines[0].split(" "))

    counter = 0
    for line in lines:
        values = line.split(" ")
        for i in range(col_len):
            data[counter, i] = float(values[i])
        counter += 1

    return data, header
        
        
def data_to_vtkPolyData(data, header, TNB=None, PT=None):
    line = vtk.vtkPolyData()
    cellArray = vtk.vtkCellArray()
    cellArray.InsertNextCell(data.shape[0])
    linePoints = vtk.vtkPoints()

    info_array = []
    for i in range(3, data.shape[1]):
        radiusArray = get_vtk_array(header[i], 1, data.shape[0])
        info_array.append(radiusArray)

    if TNB is not None:
        for i in range(3):
            radiusArray = get_vtk_array(header[i+data.shape[1]], 3, data.shape[0])
            info_array.append(radiusArray)

    if PT is not None:
        start = data.shape[1] if TNB is None else data.shape[1] + 3
        for i in range(2):
            radiusArray = get_vtk_array(header[i+start], 3, PT[0].shape[0])
            info_array.append(radiusArray)

    for i in range(data.shape[0]):
        cellArray.InsertCellPoint(i)
        linePoints.InsertNextPoint(data[i,:3])
        for j in range(3, data.shape[1]):
            info_array[j-3].SetTuple1(i, data[i, j])

    if TNB is not None:
        for i in range(data.shape[0]):
            for j in range(data.shape[1]-3, data.shape[1], 1):
                tnb_ = TNB[j - data.shape[1]][i,:]
                info_array[j].SetTuple3(i, tnb_[0], tnb_[1], tnb_[2])

    if PT is not None:
        start = data.shape[1]-3 if TNB is None else data.shape[1]
        for i in range(PT[-1].shape[0]):
            for j in range(start, start + 2, 1):
                pt_ = PT[j - start][i, :]
                info_array[j].SetTuple3(i, pt_[0], pt_[1], pt_[2])

    line.SetPoints(linePoints)
    line.SetLines(cellArray)
    for i in range(len(header) - 3):
        line.GetPointData().AddArray(info_array[i])

    return line


def get_number_of_arrays(line):
    count = 0
    names = []
    name = 0
    while name is not None:
        name = line.GetPointData().GetArrayName(count)
        if name is not None:
            names.append(name)
            count += 1

    return count, names


def ExtractSingleLine(centerlines, id, startID=0, endID=None):
    cell = vtk.vtkGenericCell()
    centerlines.GetCell(id, cell)
    N = cell.GetNumberOfPoints() if endID is None else endID + 1

    line = vtk.vtkPolyData()
    cellArray = vtk.vtkCellArray()
    cellArray.InsertNextCell(N - startID)
    linePoints = vtk.vtkPoints() 

    arrays = []
    N_, names = get_number_of_arrays(centerlines)
    for i in range(N_):
        tmp = centerlines.GetPointData().GetArray(names[i])
        tmp_comp = tmp.GetNumberOfComponents()
        radiusArray = get_vtk_array(names[i], tmp_comp, N - startID)
        arrays.append(radiusArray)

    getArray = []
    for i in range(N_):
        getArray.append(centerlines.GetPointData().GetArray(names[i]))

    for i in range(startID, N):
        cellArray.InsertCellPoint(i)
        linePoints.InsertNextPoint(cell.GetPoints().GetPoint(i))
        for j in range(N_):
            num = getArray[j].GetNumberOfComponents()
            if num == 1:
                tmp = getArray[j].GetTuple1(cell.GetPointId(i))
                arrays[j].SetTuple1(i, tmp)
            elif num == 2:
                tmp = getArray[j].GetTuple2(cell.GetPointId(i))
                arrays[j].SetTuple2(i, tmp[0], tmp[1])
            elif num == 3:
                tmp = getArray[j].GetTuple3(cell.GetPointId(i))
                arrays[j].SetTuple3(i, tmp[0], tmp[1], tmp[2])
            elif num == 9:
                tmp = getArray[j].GetTuple9(cell.GetPointId(i))
                arrays[j].SetTuple9(i, tmp[0], tmp[1], tmp[2], tmp[3], tmp[4],
                                       tmp[5], tmp[6], tmp[7], tmp[8])

    line.SetPoints(linePoints)
    line.SetLines(cellArray)
    for j in range(N_):
        line.GetPointData().AddArray(arrays[j])

    return line


def R(n, t):
    cos = math.cos
    sin = math.sin
    n1 = n[0]; n2 = n[1]; n3 = n[2]
    r = np.array([[cos(t) + n1**2 * (1 - cos(t)),   \
                   n1*n2*(1 - cos(t)) - sin(t)*n3,  \
                   n3*n1*(1 - cos(t)) + sin(t)*n2], \
                  [n1*n2*(1 - cos(t)) + sin(t)*n3,  \
                   cos(t) + n2**2*(1 - cos(t)),     \
                   n3*n2*(1 - cos(t)) - sin(t)*n1], \
                  [n1*n3*(1 - cos(t)) - sin(t)*n2,  \
                   n2*n3*(1 - cos(t)) + sin(t)*n1,  \
                   cos(t) + n3**2*(1 - cos(t))]])
    return r


def viz(centerline, points):
    """Help method during development to view the results"""
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d import Axes3D
    import numpy as np
    fig = plt.figure()
    ax = fig.gca(projection='3d')
    N = centerline.GetNumberOfCells()
    for i in range(N):
        point_ids = vtk.vtkIdList()
        centerline.GetCellPoints(i, point_ids)
        points0 = []
        for k in range(point_ids.GetNumberOfIds()):
            points0.append(centerline.GetPoint(point_ids.GetId(k)))
        arr = np.asarray(points0)
        x = arr[:,0]
        y = arr[:,1]
        z = arr[:,2]
        ax.plot(x, y, z, label=i)
        ax.legend()
        plt.hold("on")
    
    counter = 0
    for p in points:
        ax.plot([float(p[0])], [float(p[1])], [float(p[2])], "o", label=N+counter)
        ax.legend()
        plt.hold("on")
        counter += 1
    
    plt.show()
