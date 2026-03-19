
from ... import env
if env.MAYA_VERSION > 2024:
    from PySide6.QtCore import Qt, QSize
    from PySide6.QtGui import QColor, QIcon, QPixmap, QTransform, qAlpha, qGray, qRgba
else:
    from PySide2.QtCore import Qt, QSize
    from PySide2.QtGui import QColor, QIcon, QPixmap, QTransform, qAlpha, qGray, qRgba



def rotate_icon(icon, angle=90, size=QSize(24, 24)):
    """Rotate an icon by the given angle"""
    pixmap = icon.pixmap(size)
    transform = QTransform().rotate(angle)
    rotated_pixmap = pixmap.transformed(transform, Qt.SmoothTransformation)
    return QIcon(rotated_pixmap)

def desaturate_icon(icon, size=QSize(24, 24), rotation=0):
    """Convert an icon to grayscale"""
    if rotation != 0:
        icon = rotate_icon(icon, rotation, size)
    pixmap = icon.pixmap(size)
    image = pixmap.toImage()
    
    # Convert to grayscale
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixel(x, y)
            gray = qGray(pixel)
            alpha = qAlpha(pixel)
            image.setPixel(x, y, qRgba(gray, gray, gray, alpha))
    
    return QIcon(QPixmap.fromImage(image))

def colorize_icon(icon, color=QColor(170, 200, 255), size=QSize(24, 24), rotation=0):
    """Colorize an icon with the given color"""

    if rotation != 0:
        icon = rotate_icon(icon, rotation, size)
    pixmap = icon.pixmap(size)
    image = pixmap.toImage()
    
    # Apply color overlay
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixel(x, y)
            alpha = qAlpha(pixel)
            gray = qGray(pixel)
            # let's shift the gray value to the color
            # Calculate the new color based on the gray value
            new_red = int(color.red() * gray / 255)
            new_green = int(color.green() * gray / 255)
            new_blue = int(color.blue() * gray / 255)
            # Only apply color if pixel is not fully transparent
            if alpha > 0:
                image.setPixel(x, y, qRgba(new_red, new_green, new_blue, alpha))
    
    return QIcon(QPixmap.fromImage(image))

def make_toggle(icon, size=QSize(24, 24)):
    """Make the icon look like a toggle button (half black, half white)"""
    pixmap = icon.pixmap(size)
    image = pixmap.toImage()
    # find the diagonal pixels and blend them with the color
    half_width = image.width() // 2
    for y in range(image.height()):
        for x in range(image.width()):
            original_pixel = image.pixel(x, y)
            original_alpha = qAlpha(original_pixel)
            
            # Skip fully transparent pixels
            if original_alpha == 0:
                continue
            
            is_below_diagonal = x > y
            
            if x <half_width:
                # Set to black, preserving original alpha
                gray = qGray(original_pixel)
                new_pixel = qRgba(gray, gray, gray, original_alpha)
            elif x == half_width:
                # Set to black
                new_pixel = qRgba(0, 0, 0, original_alpha)
            else:
                # Set to white, preserving original alpha
                new_pixel = original_pixel
            
            image.setPixel(x, y, new_pixel)
    
    return QIcon(QPixmap.fromImage(image))