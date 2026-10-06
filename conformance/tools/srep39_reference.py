#!/usr/bin/env python3
"""Reference evaluation of SREP 39 for the expected values of srep-0039-* cases: the unevenness noise (items 1-5 of the
SREP) on a camera-facing plane at z = 0, shaded with the glTF BRDF of DEFINITIONS D11 and a D4 directional light under the
implicit camera. Derived from the SREP text, not from the engine. One difference from the D11 text: the light constant is
f * E * (n.l), without D11's factor pi, because the engine's smooth render (unevenness 0) matches that (measured on
vendor/schema-1.3 build 2d9eb13d: 0.0 to 0.5 code values over 5,000 pixels); see the commit message of the SREP 39 cases.
Usage: python3 srep39_reference.py  (prints code values of three pixels). Requires numpy."""
import warnings
warnings.filterwarnings('ignore')
import numpy as np, math
U=np.uint32
PI_FACTOR=False

def dec(c):
    c=c/255
    return c/12.92 if c<=0.04045 else ((c+0.055)/1.055)**2.4

def pcg(x):
    x=x.astype(U)
    state=x*U(747796405)+U(2891336453)
    word=((state>>((state>>U(28))+U(4)))^state)*U(277803737)
    return (word>>U(22))^word
def H(i,j,k,c):
    c=U(c&0xFFFFFFFF)
    return pcg(pcg(pcg(pcg(np.array(c,dtype=U))^k)^j)^i)
def lattice(i,j,k,c):
    h=H(i.astype(np.int32).view(U),j.astype(np.int32).view(U),k.astype(np.int32).view(U),c)
    return h.astype(np.float32).astype(np.float64)*2.0**-31-1.0
def V(q,o,seed):
    qx,qy,qz=q
    i0=np.floor(qx);j0=np.floor(qy);k0=np.floor(qz)
    tx,ty,tz=qx-i0,qy-j0,qz-k0
    wx,wy,wz=[t*t*(3-2*t) for t in (tx,ty,tz)]
    i0=i0.astype(np.int64);j0=j0.astype(np.int64);k0=k0.astype(np.int64)
    c=seed+o
    def L(di,dj,dk): return lattice(i0+di,j0+dj,k0+dk,c)
    out=0
    for di,fx in ((0,1-wx),(1,wx)):
        for dj,fy in ((0,1-wy),(1,wy)):
            for dk,fz in ((0,1-wz),(1,wz)):
                out=out+L(di,dj,dk)*fx*fy*fz
    return out
def hfun(p,s,amps,seed):
    a0,a1,a2=amps
    q=[c/s for c in p]
    return (a0*V(q,0,seed)+a1*V([2*c for c in q],1,seed)/2+a2*V([4*c for c in q],2,seed)/4)/1.75
def shade(X,Y,*,theta=0.0,A=0.0,s=8.0,seed=0,rough=0.6,base=(1,1,1),metallic=0.0,O=(320,180),light=(35.0,-20.0),E=1.0,cam=(320,180,-554.2562584220407)):
    """X,Y integer pixel arrays; returns code values (n,3) float"""
    X=np.asarray(X,float);Y=np.asarray(Y,float)
    P=np.stack([X+.5,Y+.5,np.zeros_like(X)])
    c,sn=math.cos(math.radians(theta)),math.sin(math.radians(theta))
    ax=np.array([c,sn,0.0]);ay=np.array([-sn,c,0.0]);az=np.array([0,0,1.0])
    d=P-np.array([O[0],O[1],0.0])[:,None]
    p=[np.einsum('i,i...->...',ax,d),np.einsum('i,i...->...',ay,d),np.zeros_like(X)]
    n=np.array([0,0,-1.0])[:,None]*np.ones_like(X)
    r=np.full_like(X,rough)
    if A>0:
        f=math.hypot(abs(c)+abs(sn),abs(c)+abs(sn))   # |dp/dX|+|dp/dY| componentwise: (|c|+|s|, |s|+|c|, 0)
        amps=[np.clip((s/2**o)/f-1,0,1) for o in range(3)]
        e=s/32
        def h(dp): return hfun([p[0]+dp[0],p[1]+dp[1],p[2]+dp[2]],s,amps,seed)
        gx=(h((e,0,0))-h((-e,0,0)))*s/(2*e)
        gy=(h((0,e,0))-h((0,-e,0)))*s/(2*e)
        gz=(h((0,0,e))-h((0,0,-e)))*s/(2*e)
        w=gx*ax[:,None]+gy*ay[:,None]+gz*az[:,None]
        wn=np.sum(w*n,axis=0)
        t=n-0.5*A*(w-wn*n)
        n=t/np.linalg.norm(t,axis=0)
        hv=h((0,0,0))
        r=np.clip(rough+0.25*A*hv,0.03,1.0)
    # light (D4): travel direction = R_yaw R_pitch (0,0,1); l = -travel
    yaw,pit=map(math.radians,light)
    trav=np.array([math.cos(pit)*math.sin(yaw),-math.sin(pit),math.cos(pit)*math.cos(yaw)])
    l=-trav[:,None]*np.ones_like(X)
    v=np.array(cam)[:,None]-P; v=v/np.linalg.norm(v,axis=0)
    hh=l+v; hh=hh/np.linalg.norm(hh,axis=0)
    NL=np.clip(np.sum(n*l,axis=0),0,None); NV=np.clip(np.sum(n*v,axis=0),1e-6,None)
    NH=np.clip(np.sum(n*hh,axis=0),0,None); VH=np.clip(np.sum(v*hh,axis=0),0,None)
    al=r*r; a2=al*al
    base=np.array([dec(b*255) for b in base]) if max(base)<=1 else np.array(base)
    F0=0.04*(1-metallic)+base*metallic
    F=F0[:,None]+(1-F0[:,None])*((1-VH)**5)[None,:]
    D=a2/(math.pi*(NH*NH*(a2-1)+1)**2)
    Vis=0.5/(NL*np.sqrt(NV*NV*(1-a2)+a2)+NV*np.sqrt(NL*NL*(1-a2)+a2))
    cd=base*(1-metallic)
    f=(1-F)*cd[:,None]/math.pi+F*(D*Vis)[None,:]
    col=(math.pi if PI_FACTOR else 1.0)*f*E*NL[None,:]
    col=np.clip(col,0,1)
    return (255*np.where(col<=0.0031308,12.92*col,1.055*col**(1/2.4)-0.055)).T


if __name__ == "__main__":
    print(shade(np.array([320, 100, 500]), np.array([180, 100, 260]), A=0.8, s=16, seed=3))
