#!/bin/bash
#
#
#这个脚本用来做单节点GPU组件健康检查；
#使用Nvidia DCGM工具来做GPU组件的健康检查：DCGMi health命令检查 和DCGMi diag检查


#利用DCGM工具做Background health check,默认情况下dcgm把当前节点上的GPU都看作group 0
/usr/bin/nv-hostengine
dcgmi health -g 0 -s a

#模拟GPU ECC Errors: 它不会导致dgcmi health失败，dcgmi diag level 1不会fail，但是dcgmi diag level 2 会fail
#参数-f请参考https://github.com/NVIDIA/DCGM/blob/master/dcgmlib/dcgm_fields.h
#dcgmi test --inject --gpuid 0 -f 319 -v 4

#模拟PCIe Replay Errors: 它会导致dgcmi health失败，dcgmi diag level 1不会fail，但是dcgmi diag level 2 会fail
#dcgmi test --inject --gpuid 0 -f 202 -v 99999

dcgmi health -g 0 -c | grep -i "healthy" 
if [ $? -eq 0 ] ;then
	echo "dcgmi health success"
else
	echo "fail on dcgm health check"

    exit 1
fi

#利用DCGM工具做active health check：
#dcgm diag for level 2

dcgmi diag -r 2 | grep -i "fail"
if [ $? -ne 0 ] ;then
	echo "dcgmi diag health"
else
	echo "fail on dcgm diag check"

	exit 1
fi

exit 0
