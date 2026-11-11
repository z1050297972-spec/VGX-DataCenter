# 身份不符只清陈旧记录，绝不能停止其他人的程序。
if owned; then
    stop_owned
    echo 'RDP_CONTROL stopped'
else
    rm -f -- "$pidfile"
    echo 'RDP_CONTROL absent'
fi
