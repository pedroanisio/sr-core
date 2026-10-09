/*{"ISFVSN":"2","DESCRIPTION":"SREP 67/68 kit: adds 1 to a float buffer per step; red once it reaches target, else blue",
"INPUTS":[{"NAME":"inputImage","TYPE":"image"},{"NAME":"target","TYPE":"float","DEFAULT":10}],
"PASSES":[{"TARGET":"acc","PERSISTENT":true,"FLOAT":true},{}]}*/
void main() {
    if (PASSINDEX == 0) {
        vec4 prev = IMG_NORM_PIXEL(acc, isf_FragNormCoord);
        gl_FragColor = vec4(prev.r + 1.0, 0.0, 0.0, 1.0);
    } else {
        float n = IMG_NORM_PIXEL(acc, isf_FragNormCoord).r;
        vec4 src = IMG_NORM_PIXEL(inputImage, isf_FragNormCoord);
        gl_FragColor = (n >= target - 0.5) ? vec4(1.0, 0.0, 0.0, src.a) : vec4(0.0, 0.0, 1.0, src.a);
    }
}
