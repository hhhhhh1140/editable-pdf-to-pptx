"""Convert common raster geometry to shapes; keep complex graphics as images."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .input import area, intersection

COLOR_STEP = 16


def color_hex(rgb):
    return "#" + "".join(f"{round(float(ch)):02X}" for ch in rgb)


@dataclass
class Shape:
    geometry: str
    rect: tuple
    fill: tuple
    area: int


def pure_regions(rgb, background):
    """Find compact solid regions separated by color, even inside larger art."""
    height,width=rgb.shape[:2]
    size=height*width
    background=np.asarray(background,dtype=np.int16)
    quantized=(rgb//COLOR_STEP).astype(np.int32)
    codes=quantized[:,:,0]*256 + quantized[:,:,1]*16 + quantized[:,:,2]
    hist=np.bincount(codes.ravel(),minlength=4096)
    colors=np.argsort(hist)[::-1][:35]
    max_span=max(width,height)
    shapes=[]
    for code in colors:
        if hist[code]<max(250,size*.0009):
            break
        center=np.array([code//256,code//16%16,code%16])*COLOR_STEP+COLOR_STEP/2
        if np.max(np.abs(center-background))<18:
            continue
        mask=(codes==code).astype(np.uint8)
        mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((5,7),np.uint8))
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for outline in contours:
            x,y,w,h=cv2.boundingRect(outline)
            if min(w,h)<4 or w*h<max(180,size*.00075) or w*h>size*.84:
                continue
            if min(w,h)<max_span*.012 and (max(w,h)/min(w,h)<10 or max(w,h)<max_span*.085):
                continue
            compactness=cv2.contourArea(outline)/(w*h)
            occupancy=np.mean(mask[y:y+h,x:x+w])
            component_colors=rgb[y:y+h,x:x+w][mask[y:y+h,x:x+w].astype(bool)]
            if occupancy<.67 or not len(component_colors):
                continue
            geometry="rect"
            if compactness<.88:
                if .70<compactness<.84 and .70<w/h<1.43 and len(outline)>=5:
                    geometry="oval"
                elif not .82<compactness:
                    continue
                else:
                    geometry="rounded_rect"
            rect=(x,y,x+w,y+h)
            shapes.append(Shape(geometry,rect,tuple(np.median(component_colors,axis=0)),w*h))
    selected=[]
    for shape in sorted(shapes,key=lambda s:s.area,reverse=True):
        if any(intersection(shape.rect,s.rect)>.87*min(s.area,shape.area) and
               max(s.area,shape.area)<1.22*min(s.area,shape.area) for s in selected):
            continue
        selected.append(shape)
    return selected[:180]


def outline_regions(rgb, fills):
    """Recover outlined cards even when their interior is white."""
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    height,width=gray.shape
    edges=cv2.Canny(gray,30,115)
    edges=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    outlines,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    identified=[]
    for contour in outlines:
        x,y,w,h=cv2.boundingRect(contour)
        if min(w,h)<max(width,height)*.039 or not width*height*.008<w*h<width*height*.74:
            continue
        ratio=cv2.contourArea(contour)/(w*h)
        if ratio<.88:
            continue
        rect=(x,y,x+w,y+h)
        if any(intersection(rect,s.rect)>.92*min(w*h,s.area) and
               max(w*h,s.area)<1.18*min(w*h,s.area) for s in [*fills,*identified]):
            continue
        sub=rgb[y+6:y+h-6,x+6:x+w-6]
        base=np.median(sub,axis=(0,1))
        if np.percentile(np.max(np.abs(sub.astype(np.float32)-base),axis=2),80)>24:
            continue
        boundary=contour.reshape(-1,2)
        colors=rgb[boundary[:,1],boundary[:,0]]
        distances=np.max(np.abs(colors.astype(np.float32)-base),axis=1)
        dark=colors[distances>18]
        if len(dark)<max(8,len(colors)*.14):
            continue
        stroke=tuple(np.median(dark,axis=0))
        shape=Shape("rounded_rect",rect,tuple(base),w*h)
        identified.append(shape)
        yield shape,stroke


def rounded_mask(w,h,r):
    mask=np.zeros((h,w),np.uint8)
    cv2.rectangle(mask,(r,0),(w-r-1,h-1),1,-1)
    cv2.rectangle(mask,(0,r),(w-1,h-r-1),1,-1)
    for x in (r,w-1-r):
        for y in (r,h-1-r):
            cv2.circle(mask,(x,y),r,1,-1)
    return mask.astype(bool)


def paint_shape(canvas, shape):
    x0,y0,x1,y1=shape.rect
    tile=canvas[y0:y1,x0:x1]
    color=tuple(int(v) for v in shape.fill)
    if shape.geometry=="oval":
        mask=np.zeros(tile.shape[:2],np.uint8)
        cv2.ellipse(mask,(tile.shape[1]//2,tile.shape[0]//2),
                    (tile.shape[1]//2,tile.shape[0]//2),0,0,360,1,-1)
        tile[mask.astype(bool)]=color
    elif shape.geometry=="rounded_rect":
        tile[rounded_mask(tile.shape[1],tile.shape[0],max(1,round(min(tile.shape[:2])*.10)))]=color
    else:
        tile[:]=color


def clean_region_boundaries(residual, outlines):
    for shape,_ in outlines:
        x0,y0,x1,y1=shape.rect
        # The extracted native stroke now supplies these edges.
        residual[y0:max(0,y0+4),x0:x1]=0
        residual[y1-4:y1,x0:x1]=0
        residual[y0:y1,x0:x0+4]=0
        residual[y0:y1,x1-4:x1]=0


def graphics(image, to_box, asset_path: Path, native=True):
    rgb=np.asarray(image)
    height,width=rgb.shape[:2]
    strips=np.concatenate([rgb[0],rgb[-1],rgb[:,0],rgb[:,-1]],axis=0)
    background=tuple(np.median(strips,axis=0))
    expected=np.empty_like(rgb)
    expected[:]=background
    elements=[]
    if native:
        fills=pure_regions(rgb,background)
        outlines=list(outline_regions(rgb,fills))
        if outlines:
            # Render large containers under smaller foreground shapes.
            native_shapes=[*outlines, *((s,None) for s in fills)]
            native_shapes.sort(key=lambda item:item[0].area,reverse=True)
        else:
            native_shapes=[(s,None) for s in fills]
        for i,(shape,stroke) in enumerate(native_shapes,1):
            paint_shape(expected,shape)
            elements.append(dict(type="shape",name=f"Shape {i}",shape=shape.geometry,
                                 box=to_box(shape.rect),fill=color_hex(shape.fill),
                                 line=color_hex(stroke) if stroke else "transparent",
                                 line_width=.8,radius=.10,shadow_off=True))
    else:
        outlines=[]
    error=np.max(np.abs(rgb.astype(np.int16)-expected.astype(np.int16)),axis=2)
    residual=(error>24).astype(np.uint8)
    clean_region_boundaries(residual,outlines)
    grouping=cv2.morphologyEx(residual,cv2.MORPH_CLOSE,np.ones((9,13),np.uint8))
    grouping=cv2.dilate(grouping,np.ones((5,7),np.uint8))
    count, labels, stats, _=cv2.connectedComponentsWithStats(grouping)
    for i in sorted(range(1,count),key=lambda k:int(stats[k,4]),reverse=True)[:200]:
        x,y,w,h,pixels=(int(v) for v in stats[i])
        if min(w,h)<5 or pixels<max(65,width*height*.00006):
            continue
        rect=(x,y,x+w,y+h)
        local=(labels[y:y+h,x:x+w]==i)
        true=local & (residual[y:y+h,x:x+w]!=0)
        if np.count_nonzero(true)<45:
            continue
        if native and (w>=h*12 or h>=w*12) and min(w,h)<max(width,height)*.012:
            dark=rgb[y:y+h,x:x+w][true]
            x0,y0,bw,bh=to_box(rect)
            line=(x0,y0+bh/2,x0+bw,y0+bh/2) if w>=h else (x0+bw/2,y0,x0+bw/2,y0+bh)
            elements.append(dict(type="line",name=f"Line {i}",points=line,
                                 line=color_hex(np.median(dark,axis=0)),line_width=max(.6,min(5,min(bw,bh)*.65))))
            continue
        # Transparent outside the extracted component. Give its local glow and
        # antialiased edges a smooth alpha rather than copying a bounding rectangle.
        rgba=np.empty((h,w,4),np.uint8)
        rgba[:,:,:3]=rgb[y:y+h,x:x+w]
        rgba[:,:,3]=(np.clip((error[y:y+h,x:x+w].astype(float)-4)/16,0,1)*255*local).astype(np.uint8)
        picture=asset_path/f"graphic-{i:03d}.png"
        Image.fromarray(rgba).save(picture)
        elements.append(dict(type="image",name=f"Picture {i}",box=to_box(rect),path=str(picture)))
    return color_hex(background),elements
