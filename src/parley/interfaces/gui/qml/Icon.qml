// Линейная иконка из SVG-контура в сетке 24×24. Контуры — в Icons.qml.
import QtQuick
import QtQuick.Shapes

Item {
    id: root
    property string path: ""
    property color color: Theme.text
    property real size: 20
    property real stroke: 2
    width: size
    height: size

    Shape {
        width: 24; height: 24
        scale: root.size / 24
        transformOrigin: Item.TopLeft
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: root.color
            strokeWidth: root.stroke
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: root.path }
        }
    }
}
